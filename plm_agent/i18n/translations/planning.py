"""Planning Agent translations."""
from i18n.languages import ENGLISH, CHINESE, JAPANESE, ARABIC, KOREAN, FRENCH, GERMAN, SPANISH, PORTUGUESE

TRANSLATIONS = {
    "planning.plan_reason": {
        ENGLISH: "Design tool sequence to handle user prompt",
        CHINESE: "设计工具序列以处理用户请求",
        JAPANESE: "ユーザーのプロンプトを処理するためのツールシーケンスを設計する",
        ARABIC: "تصميم تسلسل الأدوات للتعامل مع طلب المستخدم",
        KOREAN: "사용자 요청을 처리하기 위한 도구 시퀀스 설계",
        FRENCH: "Concevoir la séquence d'outils pour traiter la demande de l'utilisateur",
        GERMAN: "Werkzeugsequenz zur Bearbeitung der Benutzeranfrage entwerfen",
        SPANISH: "Diseñar secuencia de herramientas para manejar la solicitud del usuario",
        PORTUGUESE: "Projetar sequência de ferramentas para processar a solicitação do usuário",
    },
    "planning.reflection_reason": {
        ENGLISH: "Reflect on the current step execution, whether to adjust the plan and add new steps.",
        CHINESE: "反思当前步骤的执行情况，判断是否需要调整计划并添加新的步骤。",
        JAPANESE: "現在のステップの実行を振り返り、計画を調整して新しいステップを追加するかどうかを判断する。",
        ARABIC: "التفكير في تنفيذ الخطوة الحالية، وما إذا كان يجب تعديل الخطة وإضافة خطوات جديدة.",
        KOREAN: "현재 단계 실행을 반성하고 계획을 조정하여 새로운 단계를 추가할지 판단합니다.",
        FRENCH: "Réfléchir à l'exécution de l'étape actuelle, s'il faut ajuster le plan et ajouter de nouvelles étapes.",
        GERMAN: "Über die aktuelle Schrittausführung reflektieren, ob der Plan angepasst und neue Schritte hinzugefügt werden sollen.",
        SPANISH: "Reflexionar sobre la ejecución del paso actual, si se debe ajustar el plan y agregar nuevos pasos.",
        PORTUGUESE: "Refletir sobre a execução da etapa atual, se é necessário ajustar o plano e adicionar novas etapas.",
    },
    "planning.summary_reason": {
        ENGLISH: "Summarize the results of the previous steps and answer the user's question",
        CHINESE: "总结上述步骤的结果并回答用户的问题",
        JAPANESE: "前のステップの結果を要約し、ユーザーの質問に答える",
        ARABIC: "تلخيص نتائج الخطوات السابقة والإجابة على سؤال المستخدم",
        KOREAN: "이전 단계의 결과를 요약하고 사용자의 질문에 답변합니다",
        FRENCH: "Résumer les résultats des étapes précédentes et répondre à la question de l'utilisateur",
        GERMAN: "Die Ergebnisse der vorherigen Schritte zusammenfassen und die Frage des Benutzers beantworten",
        SPANISH: "Resumir los resultados de los pasos anteriores y responder la pregunta del usuario",
        PORTUGUESE: "Resumir os resultados das etapas anteriores e responder à pergunta do usuário",
    },
    "planning.download_link": {
        ENGLISH: "## Download link: [Results & Data]",
        CHINESE: "## 下载链接：[结果与数据]",
        JAPANESE: "## ダウンロードリンク：[結果とデータ]",
        ARABIC: "## رابط التحميل: [النتائج والبيانات]",
        KOREAN: "## 다운로드 링크: [결과 및 데이터]",
        FRENCH: "## Lien de téléchargement : [Résultats et données]",
        GERMAN: "## Download-Link: [Ergebnisse und Daten]",
        SPANISH: "## Enlace de descarga: [Resultados y datos]",
        PORTUGUESE: "## Link para download: [Resultados e dados]",
    },
}
