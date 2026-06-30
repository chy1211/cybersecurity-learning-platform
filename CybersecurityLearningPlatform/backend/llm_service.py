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
        self.nvidia_keys = [
            Config.NVIDIA_API_KEY_1, Config.NVIDIA_API_KEY_2, 
            Config.NVIDIA_API_KEY_3, Config.NVIDIA_API_KEY_4, 
            Config.NVIDIA_API_KEY_5, Config.NVIDIA_API_KEY_6
        ]

    @property
    def llm(self):
        if self.provider == 'nvidia':
            valid_keys = [k for k in self.nvidia_keys if k]
            if not valid_keys:
                raise ValueError("No NVIDIA API keys configured.")
            
            selected_key = random.choice(valid_keys)
            return ChatOpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=selected_key,
                model_name=Config.NVIDIA_MODEL,
                temperature=0.7,
                max_tokens=8192
            )
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
        
        response = chain.invoke(input_vars)
        
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
        
        response = chain.invoke(input_vars)
        
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
        
        response = chain.invoke(input_vars)
        
        self._log_interaction(log_file, {"template": "identify_entities", "input": input_vars}, response.content)
        
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            return json.loads(content.strip())
        except:
            return []
    
    def generate_answer_with_context(self, query, context, log_file=None):
        context_str = f"主題: {context['entity']}\n說明: {context['description']}\n\n相關知識:\n"
        for neighbor in context['neighbors']:
            context_str += f"- {neighbor['name']}: {neighbor['description']}\n"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("platform/graph_rag_answer_system.md")),
            ("user", "{query}")
        ])
        chain = prompt | self.llm
        
        input_vars = {"query": query, "context": context_str}
        self._log_interaction(log_file, {"template": "generate_answer", "input": input_vars}, "Waiting for response...")
        
        response = chain.invoke(input_vars)
        
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
        
        response = chain.invoke(input_vars)
        
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
        
        response = chain.invoke(input_vars)
        
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
