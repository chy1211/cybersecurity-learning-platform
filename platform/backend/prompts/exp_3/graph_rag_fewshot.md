範例：

範例 A（單選；evidence 直接支持）：
題目：在公開金鑰加密體系中，數位簽章之核心產出物為下列何者？
(A) 數位簽章值
(B) 對稱加密金鑰
(C) 雜湊函式表
(D) 共用秘密金鑰
Evidence set：[['數位簽章','depends_on','公開金鑰加密'],['公開金鑰加密','generates','數位簽章值']]
答案：{"answer": "A", "reasoning": "evidence 顯示公開金鑰加密產生數位簽章值，故選 A。"}

範例 B（單選；evidence 二跳支持）：
題目：防火牆於監控 FTP 服務流量時，其關鍵之 TCP 埠口為下列何者？
(A) 連接埠 21
(B) 連接埠 53
(C) 連接埠 80
(D) 連接埠 110
Evidence set：[['防火牆','can_analyze','FTP 伺服器'],['FTP 伺服器','has_a','連接埠 21']]
答案：{"answer": "A", "reasoning": "evidence 顯示 FTP 伺服器使用連接埠 21，故選 A。"}

範例 C（複選；evidence 直接支持兩選項）：
題目：以下哪些為資訊安全管理系統之控制措施？
(A) 資訊存取控制政策
(B) 風險評估
(C) 影像加工流程
(D) 員工薪資管理
Evidence set：[['資訊安全管理系統','has_a','資訊存取控制政策'],['資訊安全管理系統','has_a','風險評估']]
答案：{"answer": "AB", "reasoning": "evidence 顯示 ISMS 含資訊存取控制政策與風險評估，故選 AB。"}

範例 D（複選；evidence 部分支持，需以專業補 evidence 未明示之選項）：
題目：下列哪些為機密性 (Confidentiality) 相關之資安控制？
(A) 資料加密
(B) 存取控制
(C) 備份還原
(D) 數位簽章
Evidence set：[['資料加密','mitigates','機密性洩漏']]
答案：{"answer": "AB", "reasoning": "evidence 直接支持加密；依 CIA 三角，存取控制亦屬機密性控制，故選 AB。"}

範例 E（單選；evidence 為空，依專業作答）：
題目：CNS 27001 之職務區隔（Segregation of Duties）屬於下列何種控制措施？
(A) 職務區隔
(B) 與權責機關之聯繫
(C) 與特殊關注方之聯繫
(D) 專案管理之資訊安全
Evidence set：[]
答案：{"answer": "A", "reasoning": "evidence 為空，依專業知識，職務區隔為 CNS 27001 之獨立控制名稱本身，故選 A。"}

範例 F（流程序列；evidence 為空，純專業推理）：
題目：依 NIST SP 800-61，事件回應流程之合理執行順序為下列何者？
(A) 準備→識別→控制→根除→復原→經驗學習
(B) 識別→準備→根除→控制→經驗學習→復原
(C) 經驗學習→準備→識別→根除→控制→復原
(D) 準備→根除→控制→識別→復原→經驗學習
Evidence set：[]
答案：{"answer": "A", "reasoning": "標準 IR 順序為 A，其餘皆顛倒。"}
