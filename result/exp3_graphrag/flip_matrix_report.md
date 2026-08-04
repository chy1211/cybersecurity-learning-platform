# B4 Graph RAG base/RAG 逐題翻轉報告

> 資料範圍：新鏈正式留測 356 題；base＝未提供子圖，RAG＝提供該模型擷取之子圖。
> 本報告為離線計算，不呼叫 LLM API。TT＝對→對、TF＝對→錯、FT＝錯→對、FF＝錯→錯。

## 一、四模型翻轉矩陣總表

| 模型 | 對→對（TT） | 對→錯（TF） | 錯→對（FT） | 錯→錯（FF） | 加總 | 淨翻轉（FT−TF） |
|---|---:|---:|---:|---:|---:|---:|
| e4b | 310 | 4 | 7 | 35 | 356 | +3 |
| gptoss | 328 | 4 | 6 | 18 | 356 | +2 |
| llama70b | 320 | 4 | 1 | 31 | 356 | -3 |
| gemma31b | 336 | 1 | 3 | 16 | 356 | +2 |

## 二、各模型矩陣

### e4b

| base \ RAG | 答對 | 答錯 | 合計 |
|---|---:|---:|---:|
| 答對 | 310 | 4 | 314 |
| 答錯 | 7 | 35 | 42 |
| 合計 | 317 | 39 | 356 |

### gptoss

| base \ RAG | 答對 | 答錯 | 合計 |
|---|---:|---:|---:|
| 答對 | 328 | 4 | 332 |
| 答錯 | 6 | 18 | 24 |
| 合計 | 334 | 22 | 356 |

### llama70b

| base \ RAG | 答對 | 答錯 | 合計 |
|---|---:|---:|---:|
| 答對 | 320 | 4 | 324 |
| 答錯 | 1 | 31 | 32 |
| 合計 | 321 | 35 | 356 |

### gemma31b

| base \ RAG | 答對 | 答錯 | 合計 |
|---|---:|---:|---:|
| 答對 | 336 | 1 | 337 |
| 答錯 | 3 | 16 | 19 |
| 合計 | 339 | 17 | 356 |

## 三、負向翻轉題逐題複核表

歸因類別限定為：檢索噪音、子圖不完整、格式或指令干擾、基線已足／隨機波動。非空子圖先標為「待人工判讀」，避免僅憑有無子圖預設原因。

| 模型 | qid | 題源 | 子圖 | edges | 正解 | base | RAG | 初判 |
|---|---|---|---|---:|---|---|---|---|
| e4b | IPAS-109-TEC-081 | iPAS | empty | 0 | A | A | C | 基線已足／隨機波動 |
| e4b | IPAS-112-MGT-054 | iPAS | nonempty | 28 | A | A | C | 檢索噪音 |
| e4b | IPAS-113-MGT-022 | iPAS | nonempty | 25 | C | C | D | 子圖不完整 |
| e4b | ISN-107-032 | ISN | nonempty | 4 | C | C | B | 檢索噪音 |
| gptoss | IPAS-109-MGT-006 | iPAS | nonempty | 20 | C | C | A | 檢索噪音 |
| gptoss | IPAS-109-MGT-096 | iPAS | empty | 0 | B | B | D | 基線已足／隨機波動 |
| gptoss | IPAS-110-TEC-052 | iPAS | nonempty | 18 | A | A | B | 子圖不完整 |
| gptoss | ISN-108-040 | ISN | nonempty | 5 | B | B | D | 子圖不完整 |
| llama70b | IPAS-110-TEC-015 | iPAS | nonempty | 4 | D | D | B | 子圖不完整 |
| llama70b | IPAS-111-MGT-047 | iPAS | nonempty | 1 | B | B | C | 子圖不完整 |
| llama70b | IPAS-112-TEC-075 | iPAS | nonempty | 10 | D | D | B | 檢索噪音 |
| llama70b | ISN-109-025 | ISN | nonempty | 10 | A | A | C | 檢索噪音 |
| gemma31b | IPAS-112-MGT-072 | iPAS | nonempty | 2 | C | C | A | 子圖不完整 |

### 初判分布（待使用者複核）

| 類別 | 題數 |
|---|---:|
| 檢索噪音 | 5 |
| 子圖不完整 | 6 |
| 格式或指令干擾 | 0 |
| 基線已足／隨機波動 | 2 |
| 合計 | 13 |

llama70b 的 4 題負向翻轉初判為子圖不完整 2 題、檢索噪音 2 題；4 題子圖均非空。其子圖成功率雖高，但成功取回邊不等於取回能區辨正解與干擾選項的證據。

## 四、負向翻轉題判讀材料

### 1. e4b / IPAS-109-TEC-081

- 題源：iPAS；子圖：empty；n_edges_kept=0
- 題幹：下列何者「不」是發動中間人攻擊(Man-In-The-Middle, MITM)的必 要手段?
- 選項：A. 阻斷服務(Denial of Service, DoS)傳送端的功能；B. 偽造傳送端憑證；C. 竄改傳送端原始資訊；D. 將傳送端傳送的封包導引到駭客的機器
- 正解／base／RAG：A／A／C
- base 推理：中間人攻擊 (MITM) 的核心目標是竊聽、攔截或篡改通訊內容，而非單純地阻斷服務。雖然DoS攻擊可以作為輔助手段來分散目標的注意力或使受害者無法察覺異常，但它本身並不是發動 MITM 攻擊所「必要」的技術手段。選項 (B) 偽造憑證、(C) 竄改資訊和 (D) 導引封包（如ARP欺騙）都是實質上用於攔截或操縱通訊流，是執行 MITM 的關鍵步驟。因此，DoS 不屬於必要手段。
- RAG 推理：中間人攻擊 (MITM) 的核心目標是竊聽、攔截或篡改通訊。選項 (A)、(B) 和 (D) 都是實施 MITM 攻擊的常見技術手段（例如，DoS/DDoS 用於分散注意力或強制重定向；偽造憑證用於建立信任假象；封包導引是實現竊聽和攔截的基礎）。然而，選項 (C)「竄改傳送端原始資訊」雖然是 MITM 攻擊的**結果**之一（即資料被篡改），但它本身並不是一個「必備的手段」。MITM 攻擊可以僅用於竊聽（不竄改）或僅用於阻斷服務。因此，在所有選項中，(C) 是最不具備「必要性」的描述，因為許多 MITM 攻擊只需要攔截和監聽即可達成目的，而不需要主動修改原始資訊。
- 匹配實體：[]
- 子圖證據：(無可靠三元組)
- 初判：基線已足／隨機波動。空子圖未引入任何三元組；兩臂僅因推理取向不同而由 A 改選 C。

### 2. e4b / IPAS-112-MGT-054

- 題源：iPAS；子圖：nonempty；n_edges_kept=28
- 題幹：關於維護資料完整性之控制措施,下列敘述何者正確?
- 選項：A. 密碼學技術；B. 防火牆；C. 資料庫備份；D. 電子郵件加密
- 正解／base／RAG：A／A／C
- base 推理：evidence 為空，依資安專業知識判斷：資料完整性（Integrity）的控制措施主要用於確保資料未被未經授權地修改。在選項中，密碼學技術（如雜湊函數、數位簽章）是直接用來驗證資料是否被篡改的最核心機制。防火牆和電子郵件加密主要關注可用性或機密性；資料庫備份雖然是恢復完整性的手段，但「密碼學技術」本身才是最基礎且直接的完整性控制措施。
- RAG 推理：題目詢問維護資料完整性 (Integrity) 的控制措施。從專業知識來看，確保資料不被未授權修改或破壞的關鍵控制是備份與還原機制，因為它可以讓系統恢復到一個已知正確（完整）的狀態。Evidence set 中雖然沒有直接將「資料完整性」與某個選項連結，但它提到了「備份與還原 (Backup and Recovery)」可以『mitigates』攻擊，這最符合維護資料可信賴性和完整性的目的。密碼學技術（A）主要用於機密性或真實性；防火牆（B）和電子郵件加密（D）主要用於控制存取或傳輸的機密性/可用性，而非直接保證資料在儲存層面的完整性恢復能力。
- 匹配實體：['密碼學', '防火牆', '備份與還原']
- 子圖證據：備份與還原 --[mitigates]--> 攻擊 防火牆 --[mitigates]--> 攻擊 防火牆 --[controls]--> 內外網路 防火牆 --[controls]--> 網路系統 防火牆 --[controls]--> 網際網路 防火牆 --[controls]--> 非軍事區(dmz) 防火牆 --[controls]--> 內部電腦 防火牆 --[controls]--> 聯網裝置 防火牆 --[controls]--> 隔離區 (dmz) 防火牆 --[mitigates]--> dns 攻擊 資安人員 --[uses]--> 密碼學 windows系統更新 --[mitigates]--> 攻擊 iso/iec 9798-2 --[mitigates]--> 攻擊 關閉自動處理回條功能 --[mitigates]--> 攻擊 降低其他攻擊方式之設計 --[mitigates]--> 攻擊 定期更改密碼 --[mitigates]--> 攻擊 fail2ban --[mitigates]--> 攻擊 iptables --[mitigates]--> 攻擊 安裝更新修補程式 --[mitigates]--> 攻擊 資安人員 --[controls]--> 聯網裝置 資安人員 --[controls]--> 備援中心 資安人員 --[controls]--> 簽到系統 資安人員 --[controls]--> 資訊系統架構 資安人員 --[controls]--> 資訊資產 資安人員 --[controls]--> 加密系統 資安人員 --[uses]--> 角色為基礎管理模式 資安人員 --[uses]--> fail2ban 資安人員 --[uses]--> iptables
- 初判：檢索噪音。「備份與還原 mitigates 攻擊」等寬泛關係把模型導向 C，未直接支持資料完整性的判定。

### 3. e4b / IPAS-113-MGT-022

- 題源：iPAS；子圖：nonempty；n_edges_kept=25
- 題幹：依據 CNS 27001:2023 標準條款要求有關組織應定義及應用 資訊安全風險評鑑過程之敘述,下列何者錯誤?
- 選項：A. 建立及維持資訊安全風險準則；B. 資訊安全風險準則應包含風險接受準則以及執行資 訊安全風險評鑑之準則；C. 識別資訊安全風險包含識別資訊安全管理系統範圍 內與喪失資訊之機密性、完整性、可用性以及不可 否認性相關聯之風險；D. 分析資訊安全風險以識別風險實際發生時, 應包含 可能導致的潛在後果以及風險發生的實際可能性
- 正解／base／RAG：C／C／D
- base 推理：evidence 為空，依資安專業知識與 CNS 27001 標準要求判斷。CNS 27001 要求資訊安全風險評鑑應涵蓋機密性 (Confidentiality)、完整性 (Integrity)、可用性 (Availability) 以及**可追溯性/不可否認性 (Non-repudiation)**，但選項 C 將「不可否認性」列為與「喪失資訊之機密性、完整性、可用性相關聯的風險」，這描述不夠精確。更重要的是，在識別風險時，應關注所有可能影響 CIA+N 的資產和流程，而非僅限於「喪失資訊」。選項 A, B, D 均符合標準要求：(A) 需要建立準則；(B) 準則必須包含接受與評鑑的基準；(D) 風險分析的核心就是評估後果（Impact）和可能性（Likelihood）。因此，描述不精確或範圍過窄的 C 為最錯誤的敘述。
- RAG 推理：evidence set 僅提供了風險分析、風險識別等概念與其他標準的關聯性，但未直接提供 CNS 27001:2023 在「資訊安全風險評鑑過程」中關於各步驟（如分析、識別）的詳細定義。依據資安專業知識和 ISO/IEC 27001 的通用要求： (A) 建立及維持資訊安全風險準則，是風險管理流程的基礎要求。 (B) 風險準則應包含風險接受準則（Risk Acceptance Criteria）以及評鑑方法學（如定性/定量標準），這是正確的。 (C) 識別風險時，必須涵蓋 CIA (機密性、完整性、可用性) 以及不可否認性 (Non-repudiation)，這符合資安基礎知識。 (D) 分析資訊安全風險的目的是評估「潛在後果」和「發生可能性」，但題目描述為「以識別風險實際發生時，應包含...」。將分析階段定義為「當風險實際發生時」更接近於事件響應或事後檢討，而非風險分析本身。風險分析是預先的、假設性的評估過程，其核心是評估『可能』發生的後果和可能性，而不是描述『已經』發生時的內容。因此，敘述最為錯誤的是 D 選項。
- 匹配實體：['資訊安全風險', '風險接受', '風險識別', '資訊安全管理系統', '機密性', '風險分析', '資訊服務的風險', '風險發生可能性']
- 子圖證據：csa star --[mitigates]--> 資訊安全風險 資料加密政策 --[mitigates]--> 資訊安全風險 獎勵措施 --[mitigates]--> 資訊安全風險 iso/iec 27017 --[mitigates]--> 資訊安全風險 nis 2 directive --[mitigates]--> 資訊安全風險 iso/iec 27001 --[mitigates]--> 資訊安全風險 安全管理政策 --[mitigates]--> 資訊安全風險 風險分析 --[is_part_of]--> 風險監控過程 風險識別 --[is_part_of]--> 風險監控過程 風險管理 --[mitigates]--> 資訊安全風險 usim --[mitigates]--> 資訊安全風險 fips 140 --[mitigates]--> 資訊安全風險 服務資產 --[is_part_of]--> 資訊安全管理系統 風險分析 --[is_part_of]--> do(執行) 風險分析 --[is_part_of]--> d(do) 階段 風險分析 --[is_part_of]--> 螺旋模式 風險分析 --[is_part_of]--> 需求階段 定性法 --[is_part_of]--> 風險分析 資產分類與分級 --[is_part_of]--> 風險分析 定性法 (qualitative method) --[is_part_of]--> 風險分析 定量法 (quantitative method) --[is_part_of]--> 風險分析 企業網路電路 --[is_part_of]--> 服務資產 空調供應 --[is_part_of]--> 服務資產 網路供應 --[is_part_of]--> 服務資產 電力供應 --[is_part_of]--> 服務資產
- 初判：子圖不完整。子圖只有一般風險概念，缺少 CNS 27001:2023 條款原文與 CIA 範圍，無法區辨 C、D。

### 4. e4b / ISN-107-032

- 題源：ISN；子圖：nonempty；n_edges_kept=4
- 題幹：工商憑證是公司、分公司、有限合夥或商業用來作為網路上身分驗證用， 並提供相關安全認證服務，以保障使用者權益。請問工商憑證管理中心 （MOEACA）是隸屬於哪一個單位？
- 選項：A. 行政院；B. 內政部；C. 經濟部；D. 國土安全辦公室
- 正解／base／RAG：C／C／B
- base 推理：evidence 為空，依專業知識，工商憑證管理中心 (MOEACA) 是隸屬於經濟部（Ministry of Economic Affairs）的單位，負責提供企業相關的電子商務與身份驗證服務。
- RAG 推理：evidence set 內容與題目詢問的「工商憑證管理中心 (MOEACA) 所隸屬單位」無直接關聯。依專業知識，工商憑證（Business Certificate）通常與企業身分驗證、商業登記相關，在台灣的資訊安全和身份認證體系中，此類機構的管理權責常與內政部或其下屬單位有關，特別是涉及國民身分識別系統時。雖然 evidence 未直接指出，但根據一般公部門架構及憑證管理的主管慣例，選擇最相關的選項 B (內政部) 為最佳判斷。
- 匹配實體：['數位憑證', '企業', '身分驗證', '認證', '憑證機構']
- 子圖證據：企業 --[uses]--> 雲端運算服務 企業 --[uses]--> 第二者稽核 網路使用者 --[uses]--> 雲端運算服務 雲端運算服務 --[uses]--> 資料檔案
- 初判：檢索噪音。取回的是企業、雲端與一般身分驗證關係，與 MOEACA 隸屬經濟部無關。

### 5. gptoss / IPAS-109-MGT-006

- 題源：iPAS；子圖：nonempty；n_edges_kept=20
- 題幹：建立資訊安全管理系統(Information Security Management System, ISMS)時,下列何者「最」常由管理階層執行?
- 選項：A. 撰寫資訊安全政策；B. 執行風險分析與評鑑；C. 決定可接受風險等級；D. 擔任教育訓練講師
- 正解／base／RAG：C／C／A
- base 推理：在資訊安全管理系統的實施過程中，決定可接受風險等級屬於高階管理者（如董事會或執行長）負責的重要職能。雖然撰寫資訊安全政策亦由管理層參與，但通常是由專門的資訊安全團隊協同完成；而決策可接受風險等級則直接反映最高層對組織風險容忍度的設定，故最常由管理階層執行。
- RAG 推理：Evidence shows "管理者" (management) implements the security management policy, indicating that top management is responsible for drafting and approving the ISMS policy. While risk analysis and determining acceptable risk levels are also important tasks, they are typically carried out by specialized risk teams rather than directly by senior management during the initial establishment of an ISMS. Therefore, the most common activity performed by management in this context is writing the information‑s
- 匹配實體：['安全管理政策', '風險分析', '風險接受', '教育訓練及宣導']
- 子圖證據：安全管理政策 --[mitigates]--> 風險 安全管理政策 --[mitigates]--> 資訊安全風險 安全管理政策 --[mitigates]--> 機密外洩 安全管理政策 --[mitigates]--> 日誌篡改 安全管理政策 --[mitigates]--> 安全管理風險 安全管理政策 --[mitigates]--> 系統風險 安全管理政策 --[mitigates]--> 服務中斷損失 網路使用者 --[implements]--> 安全管理政策 管理者 --[implements]--> 安全管理政策 風險分析 --[can_analyze]--> 風險等級 風險分析 --[can_analyze]--> 事件影響性 風險分析 --[can_analyze]--> 資料檔案 風險分析 --[can_analyze]--> 電腦系統 風險分析 --[can_analyze]--> 安全隱患 風險分析 --[can_analyze]--> 潛在威脅 風險分析 --[can_analyze]--> 資訊資產 風險分析 --[can_analyze]--> 組織 風險分析 --[can_analyze]--> 風險發生可能性 員工 --[implements]--> 安全管理政策 資訊主管單位各級主管人員 --[can_analyze]--> 資料檔案
- 初判：檢索噪音。「管理者 implements 安全管理政策」使模型轉選 A，但題目問的是管理階層最常親自決定的風險接受等級。

### 6. gptoss / IPAS-109-MGT-096

- 題源：iPAS；子圖：empty；n_edges_kept=0
- 題幹：關於營運持續計畫(Business Continuity Plan, BCP)與災難復原計畫 (Disaster Recovery Plan, DRP)下列敘述何者較正確?
- 選項：A. BCP 與 DRP 的處理程序完全沒有關聯；B. BCP 較著重於營運能力的恢復；C. BCP 的資源要求通常較 DRP 為多；D. DRP 所要求的回復時間較短
- 正解／base／RAG：B／B／D
- base 推理：BCP 的核心目標是確保關鍵業務功能在災難發生後能持續運作，故其較著重於營運能力的恢復。相較之下，DRP 主要針對 IT 系統與資料的復原，兩者處理程序並非完全無關。選項 B 最能準確描述 BCP 與 DRP 的差異。
- RAG 推理：BCP（Business Continuity Plan）著重於維持或恢復整體營運功能，通常包含較長的恢復時間目標（RTO）。相對地，DRP（Disaster Recovery Plan）專注於 IT 系統與資料的快速恢復，故其 RTO 通常較短。選項 (D) 正確描述了 DRP 的回復時間較短的特性。
- 匹配實體：[]
- 子圖證據：(無可靠三元組)
- 初判：基線已足／隨機波動。空子圖未提供 BCP/DRP 證據；兩臂在 B 與 D 兩個可辯敘述間改變取捨。

### 7. gptoss / IPAS-110-TEC-052

- 題源：iPAS；子圖：nonempty；n_edges_kept=18
- 題幹：下列何者較常被採用來執行分散式阻斷服務(Distributed Denial-of- Service, DDoS)攻擊?
- 選項：A. UDP 封包攻擊；B. TCP 封包攻擊；C. HTTP 封包攻擊；D. SQL 封包攻擊
- 正解／base／RAG：A／A／B
- base 推理：在分散式阻斷服務攻擊中，最常見的手段是利用 UDP 封包進行洪水式攻擊，因為 UDP 是無連線協定，能快速產生大量封包並耗盡目標網路資源。
- RAG 推理：Evidence set contains multiple statements linking "tcp syn flood 攻擊" to harm of servers and target systems, indicating that TCP-based packet attacks (e.g., SYN floods) are a common method for executing DDoS attacks. No evidence is provided for UDP or HTTP attacks, and SQL injection is not a typical DDoS technique. Therefore, the most supported choice is TCP 封包攻擊.
- 匹配實體：['udp flood attack', 'tcp syn flood 攻擊', '漏洞利用攻擊', 'sql injection 隱碼攻擊']
- 子圖證據：tcp syn flood 攻擊 --[can_harm]--> 伺服器 sql injection 隱碼攻擊 --[can_harm]--> 伺服器 tcp syn flood 攻擊 --[can_harm]--> 目標伺服器 tcp syn flood 攻擊 --[can_harm]--> 目標系統 sql injection 隱碼攻擊 --[can_harm]--> 系統管理員帳戶 sql injection 隱碼攻擊 --[can_harm]--> 應用程式的資料庫 sql injection 隱碼攻擊 --[can_harm]--> 資料檔案 sql injection 隱碼攻擊 --[can_harm]--> 網站 sql injection 隱碼攻擊 --[can_harm]--> 網路應用程式 sql injection 隱碼攻擊 --[can_harm]--> 資料庫系統 sql injection 隱碼攻擊 --[can_harm]--> 密文 sql injection 隱碼攻擊 --[can_harm]--> 使用者資料 阻絕服務攻擊 --[can_harm]--> 伺服器 駭客攻擊 --[can_harm]--> 伺服器 自動化登入攻擊 --[can_harm]--> 伺服器 字典攻擊法 --[can_harm]--> 伺服器 dos/ddos 攻擊 --[can_harm]--> 伺服器 阻絕服務攻擊 --[can_harm]--> 目標伺服器
- 初判：子圖不完整。子圖只取回 TCP SYN flood，未取回更常見的 UDP flood 比較資訊，因而把『有證據』誤當成『最常採用』。

### 8. gptoss / ISN-108-040

- 題源：ISN；子圖：nonempty；n_edges_kept=5
- 題幹：基於全球數位化及全球化的趨勢，許多企業皆已面臨到異業的高度競爭，time to market 或是 first to market 已經企業不可避免的挑戰。對企業來說，能否有效地推動資安治理將是影響到是企業能否永續的關鍵之一。請問下列哪些標準是全球資安治理的主要依循參考？1. 資訊安全管理系統（ISMS）、2. 個人資料管理系統（PIMS）、3. 資訊服務管理系統（SMS）、4. 營運持續管理系統（BCMS）。【複選】
- 選項：A. 1-2；B. 1-2-3-4；C. 2-3；D. 1-2-4
- 正解／base／RAG：B／B／D
- base 推理：在全球資訊安全治理的框架中，常見且被廣泛採用的主要標準包括資訊安全管理系統（ISMS，ISO/IEC 27001）、個人資料管理系統（PIMS，ISO/IEC 27701）、資訊服務管理系統（SMS，ISO/IEC 20000）以及營運持續管理系統（BCMS，ISO/IEC 22301）。這四項標準共同構成了資訊安全治理的核心參考，故選項 B（1‑2‑3‑4）為最完整、最符合題意的答案。
- RAG 推理：Evidence confirms that enterprises control an Information Security Management System (ISMS). In global information‑security governance, the primary reference standards are ISO/IEC 27001 (ISMS), ISO/IEC 27701 (PIMS – a privacy extension of ISMS), and ISO/IEC 22301 (BCMS – business continuity). Among the options, only D lists 1, 2 and 4, which correspond to these three key standards. Therefore D is the most appropriate choice.
- 匹配實體：['資訊安全管理系統', '個人資料電子檔案管理', '資訊管理系統', '營運持續管理']
- 子圖證據：企業 --[controls]--> 資訊安全管理系統 高階管理層 --[controls]--> 資訊安全管理系統 企業 --[controls]--> 線上即時備援系統 企業 --[controls]--> 傳統資訊基礎設施 高階管理層 --[controls]--> 電腦系統
- 初判：子圖不完整。子圖只直接涵蓋 ISMS，缺少 PIMS、SMS 與 BCMS 的完整標準組合。

### 9. llama70b / IPAS-110-TEC-015

- 題源：iPAS；子圖：nonempty；n_edges_kept=4
- 題幹：下列何者「不」是整合式威脅管理(Unified Threat Management, UTM) 設備的常見功能?
- 選項：A. 啟用入侵防禦系統(Intrusion Prevention System, IPS),防禦異常 的網路攻擊封包；B. 管理外網與內網的各子網段交換路由；C. 以 IPSec 通訊協定建立加密傳輸路由；D. 使用 Honeypot 誘捕系統功能來蒐集與分析入侵威脅
- 正解／base／RAG：D／D／B
- base 推理：evidence 為空，依專業知識，UTM 設備通常包含防火牆、入侵防禦系統、虛擬私人網路（VPN）等功能，但不一定包含 Honeypot 誘捕系統功能。
- RAG 推理：UTM 設備的常見功能包括 IPS、VPN、防火牆等，但不包括管理外網與內網的各子網段交換路由。
- 匹配實體：['入侵程式', '外部網路', '內部網路主機', 'ipsec']
- 子圖證據：vpn --[connects_to]--> 外部網路 外部網路 --[connects_to]--> 隔離區 (dmz) 外部網路 --[connects_to]--> dmz vpn --[connects_to]--> 企業網路
- 初判：子圖不完整。僅有 VPN 與外部網路連結，未涵蓋 UTM 常見功能及 Honeypot，無法區辨 B、D。

### 10. llama70b / IPAS-111-MGT-047

- 題源：iPAS；子圖：nonempty；n_edges_kept=1
- 題幹：事件過後的檢視改善中,「不」包含下列何者?
- 選項：A. 組織政策調整；B. 滿意度調查；C. 安全設定強化；D. 教育訓練
- 正解／base／RAG：B／B／C
- base 推理：事件過後的檢視改善通常著重於組織內部的改進和增強安全性，而滿意度調查通常與事件回應無直接關係，故選 B。
- RAG 推理：evidence 顯示問卷調查是訓練的一部分，但沒有直接提到安全設定強化與檢視改善的關係。根據專業知識，檢視改善通常包括組織政策調整、滿意度調查和教育訓練等，但不一定包含安全設定強化。
- 匹配實體：['檢討與改進', '問卷調查', '安全配置', '教育訓練及宣導']
- 子圖證據：問卷調查 --[is_part_of]--> 訓練
- 初判：子圖不完整。唯一證據是問卷調查屬訓練，未涵蓋事件後檢視改善項目，模型據此錯把安全設定強化排除。

### 11. llama70b / IPAS-112-TEC-075

- 題源：iPAS；子圖：nonempty；n_edges_kept=10
- 題幹：關於應用程式軟體與資料完整性的敘述,下列何者錯誤?
- 選項：A. 使用數位簽章(Digital Signature)來驗證軟體未被 竄改；B. 僅於信任的儲存庫(Repository)取得應用程式套件；C. 整合測試流程(CI/CD)應適當隔離與存取控制以確 保安全；D. 源碼掃描可有效檢查是否遭植入惡意程式碼(如: 後門程式)
- 正解／base／RAG：D／D／B
- base 推理：evidence 為空，依專業知識，源碼掃描雖然可以檢查程式碼的安全性，但並不一定能夠有效檢查是否遭植入惡意程式碼，如後門程式。後門程式通常是指在程式碼中故意留下的安全漏洞或秘密入口，源碼掃描可能無法完全檢測到這些隱藏的安全問題。
- RAG 推理：evidence 顯示原始碼掃描可以分析程式、網路應用程式、弱點、安全隱患、原始碼、程式漏洞、注入等，但沒有證據支持僅於信任的儲存庫取得應用程式套件可以保證安全。
- 匹配實體：['數位簽章', '原始碼掃描', '後門程式']
- 子圖證據：原始碼掃描 --[can_analyze]--> 程式 原始碼掃描 --[can_analyze]--> 網路應用程式 原始碼掃描 --[can_analyze]--> 弱點 原始碼掃描 --[can_analyze]--> 安全隱患 原始碼掃描 --[can_analyze]--> 原始碼 原始碼掃描 --[can_analyze]--> 程式漏洞 原始碼掃描 --[can_analyze]--> 注入(injection) windows系統更新 --[can_analyze]--> 程式漏洞 cvss --[can_analyze]--> 弱點 檢查加密功能 --[can_analyze]--> 弱點
- 初判：檢索噪音。原始碼掃描可分析弱點的寬泛關係，被過度延伸為能有效識別惡意後門，反而強化錯誤選項 D。

### 12. llama70b / ISN-109-025

- 題源：ISN；子圖：nonempty；n_edges_kept=10
- 題幹：⼩華在⺠營企業上班，有⼀天看到同事的密碼寫在桌上，便使用同事密碼登入同 事的電腦，請問他是違反了何項法令？
- 選項：A. 刑法；B. ⺠法；C. 個人資料保護法；D. 營業秘密法
- 正解／base／RAG：A／A／C
- base 推理：evidence 為空，依專業知識，小華使用同事的密碼登入同事的電腦，侵犯了同事的電腦使用權和隱私權，可能違反了刑法中的『竊盜罪』或『侵入電腦罪』等相關條款。
- RAG 推理：evidence 顯示個人資料保護法與電腦處理相關，且當事人有權利請求停止蒐集、處理或利用之權利等，故選 C。
- 匹配實體：['密碼學', '電腦處理個人資料保護法']
- 子圖證據：當事人 --[implements]--> 電腦處理個人資料保護法 主管機關 --[implements]--> 電腦處理個人資料保護法 企業 --[implements]--> 電腦處理個人資料保護法 個人 --[implements]--> 電腦處理個人資料保護法 當事人 --[implements]--> 請求停止蒐集、處理或利用之權利 當事人 --[implements]--> 查詢或請求閱覽 當事人 --[implements]--> 請求補充或更正 當事人 --[implements]--> 請求刪除 主管機關 --[implements]--> 資通安全事件通報及應變辦法 主管機關 --[implements]--> 憑證查核
- 初判：檢索噪音。個資法相關三元組與未經授權登入的刑法判定無關，卻直接把答案拉向 C。

### 13. gemma31b / IPAS-112-MGT-072

- 題源：iPAS；子圖：nonempty；n_edges_kept=2
- 題幹：下列何者「不」是一般常見資訊安全風險管理的作業流程?
- 選項：A. 全景建立；B. 風險識別；C. 風險承受能力；D. 風險處理
- 正解／base／RAG：C／C／A
- base 推理：資訊安全風險管理的一般流程通常包含：建立環境/全景 (Context Establishment)、風險識別 (Risk Identification)、風險分析與評估 (Risk Analysis and Evaluation) 以及風險處理 (Risk Treatment)。而「風險承受能力 (Risk Appetite)」是指組織願意承擔的風險程度，它是風險評估時用來決定是否需要採取處理措施的「基準」或「參數」，而非一個作業「流程」步驟。因此 (C) 最不符合流程定義。
- RAG 推理：在資訊安全風險管理（如 ISO 31000 或 NIST SP 800-30）的標準流程中，風險識別 (Risk Identification)、風險分析 (Risk Analysis)、風險評估 (Risk Evaluation) 以及風險處理 (Risk Treatment) 是核心步驟。選項 (C) 風險承受能力 (Risk Appetite/Tolerance) 是決定風險處理策略的基準。而「全景建立」並非標準風險管理流程中的專有名詞或作業步驟，故選 A 為正確答案。
- 匹配實體：['風險管理', '風險識別', '風險接受']
- 子圖證據：風險識別 --[is_part_of]--> 風險監控過程 風險分析 --[is_part_of]--> 風險監控過程
- 初判：子圖不完整。子圖只涵蓋風險識別與分析，缺少全景建立及風險處理的完整流程，無法區辨 A、C。

## 五、機械驗算

- 模型數：4
- 每模型題數：356
- 全矩陣格數加總：1424（應為 356×4＝1424）
- 負向翻轉題（model-question pairs）：13
- qid 覆蓋：四份 eval 與四份 subgraph 皆逐一核對，均與 356 題題庫完全一致。
