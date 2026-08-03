import random
from langchain_openai import ChatOpenAI
try:
    from langchain_groq import ChatGroq
except ImportError:
    ChatGroq = None
from langchain_core.prompts import ChatPromptTemplate
from config import Config
from prompts import load_prompt
import json
import datetime
import os


class LLMService:
    def __init__(self):
        self.provider = Config.LLM_PROVIDER.lower()
        print(f"Initializing LLM Service with provider: {self.provider}")
        self.nvidia_keys = list(Config.NVIDIA_API_KEYS)
        print(f"  NVIDIA keys available: {len(self.nvidia_keys)}")

    def _nvidia_llm(self, api_key):
        return ChatOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
            model_name=Config.NVIDIA_MODEL,
            temperature=0.7,
            max_tokens=8192,
            timeout=Config.LLM_TIMEOUT_SECONDS,
            max_retries=Config.LLM_MAX_RETRIES,
        )

    @staticmethod
    def _is_key_level_error(exc):
        """金鑰失效／額度用盡：換一把金鑰重試才有意義的錯誤。"""
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
        if status in (401, 403, 429):
            return True
        text = str(exc)
        return any(marker in text for marker in ("401", "403", "429", "Authorization failed"))

    def _invoke(self, prompt, input_vars):
        """呼叫模型；NVIDIA 端遇到金鑰層級錯誤自動換下一把金鑰。

        六把金鑰中只要有一把失效（實測 KEY_2 已 403），原本的 random.choice
        就會隨機讓使用者吃到 500，因此改成逐把 failover。
        """
        if self.provider != 'nvidia':
            return (prompt | self.llm).invoke(input_vars)

        keys = [k for k in self.nvidia_keys if k]
        if not keys:
            raise ValueError("No NVIDIA API keys configured.")

        last_error = None
        for api_key in random.sample(keys, len(keys)):
            try:
                return (prompt | self._nvidia_llm(api_key)).invoke(input_vars)
            except Exception as exc:
                if not self._is_key_level_error(exc):
                    raise
                last_error = exc
                print(f"NVIDIA key rejected ({type(exc).__name__}); trying next key.")
        raise last_error

    @property
    def llm(self):
        if self.provider == 'nvidia':
            valid_keys = [k for k in self.nvidia_keys if k]
            if not valid_keys:
                raise ValueError("No NVIDIA API keys configured.")
            return self._nvidia_llm(random.choice(valid_keys))
        elif self.provider == 'groq':
            if not ChatGroq:
                raise ImportError("langchain-groq is not installed. Please install it to use Groq.")
            return ChatGroq(
                temperature=0.7, 
                groq_api_key=Config.GROQ_API_KEY, 
                model_name=Config.GROQ_MODEL
            )
        elif self.provider == 'lm_studio':
            return ChatOpenAI(
                base_url=Config.LM_STUDIO_BASE_URL,
                api_key="lm-studio",
                temperature=0,
                model_name=Config.LM_STUDIO_MODEL
            )
        else:
            return ChatOpenAI(
                model="gpt-4o", 
                temperature=0.7, 
                openai_api_key=Config.OPENAI_API_KEY
            )

    def _log_interaction(self, log_file, prompt_input, response_content):
        """Helper to log LLM interaction to file"""
        if not log_file:
            return
            
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write("\n" + "="*50 + "\n")
                f.write(f"LLM Interaction Time: {datetime.datetime.now().isoformat()}\n")
                f.write("-" * 20 + " PROMPT INPUT " + "-" * 20 + "\n")
                f.write(json.dumps(prompt_input, ensure_ascii=False, indent=2))
                f.write("\n" + "-" * 20 + " LLM RESPONSE " + "-" * 20 + "\n")
                f.write(str(response_content))
                f.write("\n" + "="*50 + "\n")
        except Exception as e:
            print(f"Error writing to log file: {e}")
    
    def explain_mistake(self, question, user_answer, correct_answer, context="", log_file=None):
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/explain_mistake_system.md")),
            ("user", load_prompt("platform/explain_mistake_user.md"))
        ])
        chain = prompt | self.llm
        
        # Log input
        input_vars = {
            "question": question,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "context": context
        }
        self._log_interaction(log_file, {"template": "explain_mistake", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        # Log response
        self._log_interaction(log_file, {"template": "explain_mistake", "input": input_vars}, response.content)
        
        return response.content

    def extract_entities_from_text(self, text, log_file=None):
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/extract_entities_system.md")),
            ("user", "{text}")
        ])
        chain = prompt | self.llm
        
        input_vars = {"text": text}
        self._log_interaction(log_file, {"template": "extract_entities", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        self._log_interaction(log_file, {"template": "extract_entities", "input": input_vars}, response.content)
        
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
        except:
            return []
    
    def identify_entities_in_query(self, query, log_file=None):
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/identify_entities_system.md")),
            ("user", "{query}")
        ])
        chain = prompt | self.llm
        
        input_vars = {"query": query}
        self._log_interaction(log_file, {"template": "identify_entities", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        self._log_interaction(log_file, {"template": "identify_entities", "input": input_vars}, response.content)
        
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            return json.loads(content.strip())
        except:
            return []
    
    def generate_answer_with_context(self, query, context, log_file=None):
        if isinstance(context, dict) and "edges" in context:
            context_str = self.build_graph_context_string(context)
        else:
            # 舊格式（單一實體＋鄰居清單）保留相容
            context_str = f"主題: {context['entity']}\n說明: {context.get('description')}\n\n相關知識:\n"
            for neighbor in context.get('neighbors', []):
                context_str += f"- {neighbor['name']}: {neighbor.get('description')}\n"

        prompt = ChatPromptTemplate.from_messages([
    @staticmethod
    def build_graph_context_string(graph_context):
        """把子圖攤成三元組文字，這份字串就是模型實際看到的圖內容。

        平台格式的圖沒有 description 屬性，語意在關係型別與節點型別上，
        因此 context 以「來源 --[關係]--> 目標」呈現，而非名稱＋描述。
        """
        seeds = graph_context.get("seeds") or []
        edges = graph_context.get("edges") or []
        stats = graph_context.get("stats") or {}

        lines = ["【問題命中的知識點】"]
        if seeds:
            for seed in seeds:
                lines.append(f"- {seed['name']}（類型：{seed.get('type') or 'unknown'}）")
        else:
            lines.append("- （無明確命中）")

        lines.append("")
        lines.append(f"【知識圖譜關係｜共 {len(edges)} 條，取自命中知識點的一跳鄰域】")
        for index, edge in enumerate(edges, start=1):
            sources = edge.get("source_files") or []
            source_note = f"（來源：{'、'.join(sources)}）" if sources else ""
            lines.append(
                f"{index}. {edge['source']} --[{edge['relation']}]--> {edge['target']}{source_note}"
            )

        if stats.get("truncated"):
            lines.append("")
            lines.append(
                f"（註：命中鄰域共 {stats.get('total_edges_found')} 條關係，"
                f"已依相關性取前 {len(edges)} 條）"
            )
        return "\n".join(lines)

            ("system", load_prompt("platform/graph_rag_answer_system.md")),
            ("user", "{query}")
        ])
        chain = prompt | self.llm
        
        input_vars = {"query": query, "context": context_str}
        self._log_interaction(log_file, {"template": "generate_answer", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        self._log_interaction(log_file, {"template": "generate_answer", "input": input_vars}, response.content)
        
        return response.content

    def generate_quiz(self, entity_name, context_json, log_file=None):
        prompt_text = load_prompt("platform/generate_quiz_user.md")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/generate_quiz_system.md")),
            ("user", prompt_text)
        ])
        
        chain = prompt | self.llm
        
        # Convert context_json to string if it's a dict/list
        context_str = json.dumps(context_json, ensure_ascii=False) if isinstance(context_json, (dict, list)) else str(context_json)
        
        # Truncate context if too long
        if len(context_str) > 10000:
            context_str = context_str[:10000] + "...(truncated)"
            
        input_vars = {"entity": entity_name, "context": context_str}
        self._log_interaction(log_file, {"template": "generate_quiz", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        self._log_interaction(log_file, {"template": "generate_quiz", "input": input_vars}, response.content)
        
        try:
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            questions = json.loads(content.strip())
            
            # Add debug info if enabled
            import os
            if os.environ.get('SHOW_DEBUG_ANSWERS') == 'True':
                for q in questions:
                    # Try to find the correct answer text
                    try:
                        correct_idx = int(q.get('correctAnswer', 0))
                        options = q.get('options', [])
                        if 0 <= correct_idx < len(options):
                            q['debugInfo'] = {
                                "correctAnswerText": options[correct_idx],
                                "source": f"Generated for {entity_name}"
                            }
                    except:
                        pass
            
            return questions
        except Exception as e:
            print(f"Error parsing quiz JSON: {e}")
            return []

    def generate_batch_quiz(self, entities_context, log_file=None):
        """
        Generate questions for multiple entities in one go.
        entities_context: list of dicts, e.g. [{'entity': 'Name', 'context': '...'}]
        """
        prompt_text = load_prompt("platform/generate_batch_quiz_user.md")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/generate_quiz_system.md")),
            ("user", prompt_text)
        ])
        
        chain = prompt | self.llm
        
        # Build context string
        full_context_str = ""
        for item in entities_context:
            full_context_str += f"\n主題：{item['entity']}\n參考內容：{item['context']}\n-------------------\n"
            
        # Truncate
        if len(full_context_str) > 12000:
             full_context_str = full_context_str[:12000] + "...(truncated)"
             
        input_vars = {"context_str": full_context_str}
        self._log_interaction(log_file, {"template": "generate_batch_quiz", "input": input_vars}, "Waiting for response...")
        
        response = self._invoke(prompt, input_vars)
        
        self._log_interaction(log_file, {"template": "generate_batch_quiz", "input": input_vars}, response.content)
        
        try:
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            questions = json.loads(content.strip())
            
            # Add debug info
            import os
            if os.environ.get('SHOW_DEBUG_ANSWERS') == 'True':
                for q in questions:
                    try:
                        correct_idx = int(q.get('correctAnswer', 0))
                        options = q.get('options', [])
                        entity_name = q.get('entity_name', 'Unknown')
                        if 0 <= correct_idx < len(options):
                            q['debugInfo'] = {
                                "correctAnswerText": options[correct_idx],
                                "source": f"Generated for {entity_name}"
                            }
                    except:
                        pass
            return questions
        except Exception as e:
            print(f"Error parsing batch quiz JSON: {e}")
            return []
