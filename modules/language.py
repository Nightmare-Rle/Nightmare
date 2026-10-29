"""Selected output language.

The language dropdown picks the language NIGHTMARE answers in. That is a
setting about the assistant, not about the message: typing English while
Italian is selected must still get an Italian reply.

This module owns the list (previously duplicated in the GUI) and the fixed
strings the app speaks without asking the model, so they follow the selected
language too instead of always coming out in English.
"""

LANGUAGES = {
    "English": "en", "Spanish": "es", "French": "fr", "German": "de",
    "Italian": "it", "Portuguese": "pt", "Japanese": "ja", "Korean": "ko",
    "Chinese": "zh", "Russian": "ru", "Arabic": "ar", "Hindi": "hi",
    "Tagalog": "tl", "Vietnamese": "vi", "Thai": "th",
}

CODES = set(LANGUAGES.values())

_NAME_OF = {code: name for name, code in LANGUAGES.items()}

# Native endonyms, used to point the model at a language by its own name
# (writing "Japanese" to a small model is weaker than "Japanese").
NATIVE = {
    "en": "English", "es": "Español", "fr": "Français", "de": "Deutsch",
    "it": "Italiano", "pt": "Português", "ja": "日本語", "ko": "한국어",
    "zh": "中文", "ru": "Русский", "ar": "العربية", "hi": "हिन्दी",
    "tl": "Tagalog", "vi": "Tiếng Việt", "th": "ไทย",
}

STRINGS = {
    "greeting": {
        "en": "Hello. How can I help?",
        "es": "Hola, ¿en qué puedo ayudarte?",
        "fr": "Bonjour, comment puis-je vous aider ?",
        "de": "Hallo, wie kann ich helfen?",
        "it": "Ciao, come posso aiutarti?",
        "pt": "Olá, como posso ajudar?",
        "ja": "こんにちは。何かお手伝いしましょうか？",
        "ko": "안녕하세요. 무엇을 도와드릴까요?",
        "zh": "你好。我能帮你做什么？",
        "ru": "Здравствуйте. Чем могу помочь?",
        "ar": "مرحبًا. كيف يمكنني مساعدتك؟",
        "hi": "नमस्ते। मैं आपकी कैसे मदद कर सकता हूँ?",
        "tl": "Kumusta. Paano kita matutulungan?",
        "vi": "Xin chào. Tôi có thể giúp gì?",
        "th": "สวัสดี มีอะไรให้ช่วยไหม",
    },
    "reset": {
        "en": "Conversation reset. How can I help?",
        "es": "Conversación reiniciada. ¿En qué puedo ayudarte?",
        "fr": "Conversation réinitialisée. Comment puis-je vous aider ?",
        "de": "Unterhaltung zurückgesetzt. Wie kann ich helfen?",
        "it": "Conversazione azzerata. Come posso aiutarti?",
        "pt": "Conversa reiniciada. Como posso ajudar?",
        "ja": "会話をリセットしました。何かお手伝いしましょうか？",
        "ko": "대화를 초기화했습니다. 무엇을 도와드릴까요?",
        "zh": "对话已重置。我能帮你做什么？",
        "ru": "Диалог сброшен. Чем могу помочь?",
        "ar": "تمت إعادة ضبط المحادثة. كيف يمكنني مساعدتك؟",
        "hi": "बातचीत रीसेट कर दी गई। मैं आपकी कैसे मदद कर सकता हूँ?",
        "tl": "Na-reset ang usapan. Paano kita matutulungan?",
        "vi": "Đã đặt lại cuộc trò chuyện. Tôi có thể giúp gì?",
        "th": "รีเซ็ตการสนทนาแล้ว มีอะไรให้ช่วยไหม",
    },
    "lang_switched": {
        "en": "Language switched to {name}. I will answer in this language from now on.",
        "es": "Idioma cambiado a {name}. A partir de ahora responderé en este idioma.",
        "fr": "Langue changée pour {name}. Je répondrai désormais dans cette langue.",
        "de": "Sprache auf {name} umgestellt. Ich antworte ab jetzt in dieser Sprache.",
        "it": "Lingua impostata su {name}. Da ora risponderò in questa lingua.",
        "pt": "Idioma alterado para {name}. A partir de agora responderei neste idioma.",
        "ja": "言語を{name}に切り替えました。これ以降は日本語で答えます。",
        "ko": "언어를 {name}(으)로 변경했습니다. 이제 이 언어로 답하겠습니다.",
        "zh": "已切换到{name}。之后我会用这种语言回答。",
        "ru": "Язык изменён на {name}. Теперь я отвечаю на этом языке.",
        "ar": "تم تغيير اللغة إلى {name}. سأجيب من الآن فصاعدًا بهذه اللغة.",
        "hi": "भाषा {name} में बदल दी गई। अब से मैं इसी भाषा में उत्तर दूँगा।",
        "tl": "Nilipat ang wika sa {name}. Mula ngayon ay sasagot ako sa wikang ito.",
        "vi": "Đã chuyển sang {name}. Từ giờ tôi sẽ trả lời bằng ngôn ngữ này.",
        "th": "เปลี่ยนภาษาเป็น {name} แล้ว ต่อไปนี้ฉันจะตอบเป็นภาษานี้",
    },
    "name_learned": {
        "en": "Understood. I'll remember you as {name}.",
        "es": "Entendido. Te recordaré como {name}.",
        "fr": "Compris. Je me souviendrai de vous comme {name}.",
        "de": "Verstanden. Ich merke mir, dass du {name} heißt.",
        "it": "Ho capito. Ti ricorderò come {name}.",
        "pt": "Entendido. Vou lembrar você como {name}.",
        "ja": "了解しました。{name}として記憶します。",
        "ko": "알겠습니다. {name}(으)로 기억하겠습니다.",
        "zh": "明白。我会记住你是{name}。",
        "ru": "Понятно. Буду помнить вас как {name}.",
        "ar": "فهمت. سأتذكر أنك {name}.",
        "hi": "समझ गया। मैं आपको {name} के रूप में याद रखूँगा।",
        "tl": "Naiintindihan ko. Tandaan ko na ikaw ay {name}.",
        "vi": "Đã hiểu. Tôi sẽ nhớ bạn là {name}.",
        "th": "เข้าใจแล้ว จะจำว่าคุณคือ {name}",
    },
    "fact_learned": {
        "en": "Noted. I'll remember that {subject} is {value}.",
        "es": "Anotado. Recordaré que {subject} es {value}.",
        "fr": "Noté. Je me souviendrai que {subject} est {value}.",
        "de": "Notiert. Ich merke mir, dass {subject} {value} ist.",
        "it": "Annotato. Ricorderò che {subject} è {value}.",
        "pt": "Anotado. Vou lembrar que {subject} é {value}.",
        "ja": "メモしました。{subject}は{value}だと記憶します。",
        "ko": "기록했습니다. {subject}은(는) {value}이라고 기억하겠습니다.",
        "zh": "已记录。我会记住{subject}是{value}。",
        "ru": "Записано. Буду помнить, что {subject} — {value}.",
        "ar": "تم التسجيل. سأتذكر أن {subject} هو {value}.",
        "hi": "नोट कर लिया। मैं याद रखूँगा कि {subject} {value} है।",
        "tl": "Tandaan na. Tandaan ko na {subject} ay {value}.",
        "vi": "Đã ghi nhận. Tôi sẽ nhớ rằng {subject} là {value}.",
        "th": "บันทึกแล้ว จะจำว่า {subject} คือ {value}",
    },
    "pref_learned": {
        "en": "Noted. I'll remember that.",
        "es": "Anotado. Lo recordaré.",
        "fr": "Noté. Je m'en souviendrai.",
        "de": "Notiert. Ich merke mir das.",
        "it": "Annotato. Lo ricorderò.",
        "pt": "Anotado. Vou lembrar.",
        "ja": "メモしました。",
        "ko": "기록했습니다.",
        "zh": "已记录。",
        "ru": "Записано.",
        "ar": "تم التسجيل.",
        "hi": "नोट कर लिया।",
        "tl": "Tandaan na.",
        "vi": "Đã ghi nhận.",
        "th": "บันทึกแล้ว",
    },
    "memory_empty": {
        "en": "My memory is empty so far.",
        "es": "Mi memoria está vacía por ahora.",
        "fr": "Ma mémoire est encore vide.",
        "de": "Mein Gedächtnis ist noch leer.",
        "it": "La mia memoria è ancora vuota.",
        "pt": "A minha memória ainda está vazia.",
        "ja": "記憶はまだ空です。",
        "ko": "제 기억은 아직 비어 있습니다.",
        "zh": "我的记忆目前是空的。",
        "ru": "Моя память пока пуста.",
        "ar": "ذاكرتي فارغة حتى الآن.",
        "hi": "मेरी याददाश्त अभी खाली है।",
        "tl": "Wala pa akong memorya.",
        "vi": "Ký ức của tôi hiện còn trống.",
        "th": "ความจำของฉันยังว่างอยู่",
    },
    "memory_recall": {
        "en": "Here's what I remember:\n{ctx}",
        "es": "Esto es lo que recuerdo:\n{ctx}",
        "fr": "Voici ce dont je me souviens :\n{ctx}",
        "de": "Das merke ich mir:\n{ctx}",
        "it": "Ecco cosa ricordo:\n{ctx}",
        "pt": "Eis o que lembro:\n{ctx}",
        "ja": "覚えていることは次のとおりです:\n{ctx}",
        "ko": "제가 기억하는 내용은 다음과 같습니다:\n{ctx}",
        "zh": "我记得以下内容：\n{ctx}",
        "ru": "Вот что я помню:\n{ctx}",
        "ar": "هذا ما أتذكره:\n{ctx}",
        "hi": "यह मुझे याद है:\n{ctx}",
        "tl": "Ito ang naaalala ko:\n{ctx}",
        "vi": "Đây là những gì tôi nhớ:\n{ctx}",
        "th": "สิ่งที่ฉันจำได้:\n{ctx}",
    },
    "alias_saved": {
        "en": "Alias saved: \"{alias}\" will run \"{command}\".",
        "es": "Alias guardado: \"{alias}\" ejecutará \"{command}\".",
        "fr": "Alias enregistré : \"{alias}\" exécutera \"{command}\".",
        "de": "Alias gespeichert: \"{alias}\" führt \"{command}\" aus.",
        "it": "Alias salvato: \"{alias}\" eseguirà \"{command}\".",
        "pt": "Alias salvo: \"{alias}\" executará \"{command}\".",
        "ja": "エイリアスを保存しました：「{alias}」は「{command}」を実行します。",
        "ko": "별칭 저장됨: \"{alias}\"는 \"{command}\"를 실행합니다.",
        "zh": "别名已保存：“{alias}”将运行“{command}”。",
        "ru": "Псевдоним сохранён: \"{alias}\" выполнит \"{command}\".",
        "ar": "تم حفظ الاسم المستعار: \"{alias}\" سينفّذ \"{command}\".",
        "hi": "उपनाम सहेजा गया: \"{alias}\" \"{command}\" चलाएगा।",
        "tl": "Naili ang alias: \"{alias}\" ay magpapatakbo ng \"{command}\".",
        "vi": "Đã lưu bí danh: \"{alias}\" sẽ chạy \"{command}\".",
        "th": "บันทึกชื่อย่อแล้ว: \"{alias}\" จะรัน \"{command}\"",
    },
    "face_matched": {
        "en": "Face recognised. Welcome back.",
        "es": "Rostro reconocido. Bienvenido de nuevo.",
        "fr": "Visage reconnu. Bon retour.",
        "de": "Gesicht erkannt. Willkommen zurück.",
        "it": "Volto riconosciuto. Bentornato.",
        "pt": "Rosto reconhecido. Bem-vindo de volta.",
        "ja": "顔を認識しました。おかえりなさい。",
        "ko": "얼굴을 인식했습니다. 다시 오신 것을 환영합니다.",
        "zh": "已识别您的面孔。欢迎回来。",
        "ru": "Лицо распознано. С возвращением.",
        "ar": "تم التعرّف على الوجه. أهلاً بعودتك.",
        "hi": "चेहरा पहचान लिया गया। वापसी पर स्वागत है।",
        "tl": "Nkilala ang mukha. Maligayang pagbalik.",
        "vi": "Đã nhận diện khuôn mặt. Chào mừng bạn trở lại.",
        "th": "จดจำใบหน้าแล้ว ยินดีต้อนรับกลับมา",
    },
    "face_enroll_needed": {
        "en": "Face lock is on, but no face is enrolled yet. Look at the camera to enrol.",
        "es": "El bloqueo facial está activo, pero no hay ningún rostro registrado. Mira a la cámara para registrarlo.",
        "fr": "Le verrouillage facial est actif, mais aucun visage n'est enregistré. Regardez la caméra pour vous enregistrer.",
        "de": "Die Gesichtssperre ist aktiv, aber es ist noch kein Gesicht registriert. Schauen Sie in die Kamera, um sich zu registrieren.",
        "it": "Il blocco facciale è attivo, ma nessun volto è ancora registrato. Guarda la fotocamera per registrarti.",
        "pt": "O bloqueio facial está ativo, mas nenhum rosto foi registrado. Olhe para a câmera para se registrar.",
        "ja": "顔ロックは有効ですが、まだ顔が登録されていません。カメラに向かって登録してください。",
        "ko": "얼굴 잠금이 켜져 있지만 아직 등록된 얼굴이 없습니다. 카메라를 바라보며 등록하세요.",
        "zh": "人脸锁已开启，但尚未录入任何面孔。请面对摄像头完成录入。",
        "ru": "Блокировка по лицу включена, но ни одного лица не зарегистрировано. Посмотрите в камеру, чтобы зарегистрироваться.",
        "ar": "قفل الوجه مُفعّل، لكن لم يتم تسجيل أي وجه بعد. انظر إلى الكاميرا للتسجيل.",
        "hi": "फेस लॉक चालू है, लेकिन अभी कोई चेहरा दर्ज नहीं है। दर्ज करने के लिए कैमरे की ओर देखें।",
        "tl": "Naka-on ang face lock, pero walang nare-enrol na mukha. Tingnan ang kamera para mag-enrol.",
        "vi": "Khóa khuôn mặt đang bật, nhưng chưa đăng ký khuôn mặt nào. Hãy nhìn vào camera để đăng ký.",
        "th": "ล็อกใบหน้าเปิดอยู่ แต่ยังไม่ได้ลงทะเบียนใบหน้าใด กรุณามองกล้องเพื่อลงทะเบียน",
    },
    "face_enrolling": {
        "en": "Enrolling your face — hold still and look straight at the camera.",
        "es": "Registrando tu rostro: quédate quieto y mira de frente a la cámara.",
        "fr": "Enregistrement de votre visage — restez immobile et regardez la caméra.",
        "de": "Gesicht wird registriert – stillhalten und direkt in die Kamera sehen.",
        "it": "Sto registrando il tuo volto: resta fermo e guarda dritto in camera.",
        "pt": "Registrando seu rosto — fique parado e olhe direto para a câmera.",
        "ja": "顔を登録しています。動かず、カメラを正面から見てください。",
        "ko": "얼굴을 등록하는 중입니다. 움직이지 말고 카메라를 정면으로 바라보세요.",
        "zh": "正在录入您的面孔——请保持不动，正视摄像头。",
        "ru": "Идёт регистрация лица — не двигайтесь и смотрите прямо в камеру.",
        "ar": "جارٍ تسجيل وجهك — ابقَ ثابتًا وانظر إلى الكاميرا مباشرة.",
        "hi": "आपका चेहरा दर्ज किया जा रहा है — स्थिर रहें और कैमरे की ओर देखें।",
        "tl": "Nire-enrol ang mukha mo — wag maggalaw at tingnan ang kamera nang tuwiran.",
        "vi": "Đang đăng ký khuôn mặt của bạn — hãy đứng yên và nhìn thẳng vào camera.",
        "th": "กำลังลงทะเบียนใบหน้าของคุณ — อย่าขยับ และมองกล้องโดยตรง",
    },
    "face_enrolled": {
        "en": "Face enrolled from {samples} samples. Face lock is active.",
        "es": "Rostro registrado con {samples} muestras. El bloqueo facial está activo.",
        "fr": "Visage enregistré à partir de {samples} échantillons. Le verrouillage facial est actif.",
        "de": "Gesicht aus {samples} Aufnahmen registriert. Die Gesichtssperre ist aktiv.",
        "it": "Volto registrato da {samples} campioni. Il blocco facciale è attivo.",
        "pt": "Rosto registrado a partir de {samples} amostras. O bloqueio facial está ativo.",
        "ja": "{samples} 件のサンプルから顔を登録しました。顔ロックが有効です。",
        "ko": "{samples}개 샘플로 얼굴을 등록했습니다. 얼굴 잠금이 활성화되었습니다.",
        "zh": "已从 {samples} 个样本录入面孔。人脸锁已启用。",
        "ru": "Лицо зарегистрировано по {samples} образцам. Блокировка активна.",
        "ar": "تم تسجيل الوجه من {samples} عينة. قفل الوجه مُفعّل.",
        "hi": "{samples} नमूनों से चेहरा दर्ज किया गया। फेस लॉक सक्रिय है।",
        "tl": "Nai-enrol ang mukha mula sa {samples} na sample. Aktibo na ang face lock.",
        "vi": "Đã đăng ký khuôn mặt từ {samples} mẫu. Khóa khuôn mặt đang bật.",
        "th": "ลงทะเบียนใบหน้าจาก {samples} ตัวอย่างแล้ว ล็อกใบหน้าทำงานอยู่",
    },
    "face_enroll_failed": {
        "en": "Could not enrol your face: {reason}",
        "es": "No se pudo registrar tu rostro: {reason}",
        "fr": "Impossible d'enregistrer votre visage : {reason}",
        "de": "Gesicht konnte nicht registriert werden: {reason}",
        "it": "Non è stato possibile registrare il tuo volto: {reason}",
        "pt": "Não foi possível registrar seu rosto: {reason}",
        "ja": "顔を登録できませんでした: {reason}",
        "ko": "얼굴을 등록할 수 없습니다: {reason}",
        "zh": "无法录入您的面孔：{reason}",
        "ru": "Не удалось зарегистрировать лицо: {reason}",
        "ar": "تعذّر تسجيل وجهك: {reason}",
        "hi": "आपका चेहरा दर्ज नहीं हो सका: {reason}",
        "tl": "Hindi na-enrol ang mukha mo: {reason}",
        "vi": "Không thể đăng ký khuôn mặt: {reason}",
        "th": "ไม่สามารถลงทะเบียนใบหน้าได้: {reason}",
    },
    "face_nomatch": {
        "en": "That face is not yours. Locking the laptop.",
        "es": "Ese rostro no es el tuyo. Bloqueando el portátil.",
        "fr": "Ce visage n'est pas le vôtre. Verrouillage de l'ordinateur.",
        "de": "Dieses Gesicht ist nicht Ihr. Laptop wird gesperrt.",
        "it": "Quel volto non è il tuo. Sto bloccando il portatile.",
        "pt": "Esse rosto não é o seu. Bloqueando o notebook.",
        "ja": "その顔はあなたのものではありません。ノートパソコンをロックします。",
        "ko": "그 얼굴은 당신 것이 아닙니다. 노트북을 잠급니다.",
        "zh": "该面孔不是您本人。正在锁定电脑。",
        "ru": "Это лицо не ваше. Блокирую ноутбук.",
        "ar": "هذا الوجه ليس وجهك. جارٍ قفل الحاسوب.",
        "hi": "यह चेहरा आपका नहीं है। लैपटॉप लॉक किया जा रहा है।",
        "tl": "Hindi iyo ang mukha mo. Nilock ang laptop.",
        "vi": "Khuôn mặt đó không phải của bạn. Đang khóa máy tính.",
        "th": "ใบหน้านั้นไม่ใช่ของคุณ กำลังล็อกเครื่อง",
    },
    "face_noface": {
        "en": "No face recognised. Locking the laptop.",
        "es": "No se reconoció ningún rostro. Bloqueando el portátil.",
        "fr": "Aucun visage reconnu. Verrouillage de l'ordinateur.",
        "de": "Kein Gesicht erkannt. Laptop wird gesperrt.",
        "it": "Nessun volto riconosciuto. Sto bloccando il portatile.",
        "pt": "Nenhum rosto reconhecido. Bloqueando o notebook.",
        "ja": "顔を認識できませんでした。ノートパソコンをロックします。",
        "ko": "얼굴을 인식하지 못했습니다. 노트북을 잠급니다.",
        "zh": "未识别到任何面孔。正在锁定电脑。",
        "ru": "Лицо не распознано. Блокирую ноутбук.",
        "ar": "لم يتم التعرّف على أي وجه. جارٍ قفل الحاسوب.",
        "hi": "कोई चेहरा पहचाना नहीं गया। लैपटॉप लॉक किया जा रहा है।",
        "tl": "Walang nkilalang mukha. Nilock ang laptop.",
        "vi": "Không nhận diện được khuôn mặt nào. Đang khóa máy tính.",
        "th": "ไม่พบใบหน้าที่จดจำได้ กำลังล็อกเครื่อง",
    },
    "face_failopen": {
        "en": "Face check could not run ({reason}). Letting you in — it will not lock the laptop.",
        "es": "No se pudo ejecutar la comprobación facial ({reason}). Te dejo pasar: no bloqueará el portátil.",
        "fr": "La vérification faciale n'a pas pu s'exécuter ({reason}). Accès autorisé : l'ordinateur ne sera pas verrouillé.",
        "de": "Gesichtssperre konnte nicht ausgeführt werden ({reason}). Zugang erlaubt – der Laptop wird nicht gesperrt.",
        "it": "Il controllo facciale non è stato eseguito ({reason}). Ti lascio entrare: non bloccherà il portatile.",
        "pt": "A verificação facial não pôde ser executada ({reason}). Liberando o acesso — não vai bloquear o notebook.",
        "ja": "顔認証を実行できませんでした（{reason}）。入室を許可します — ロックしません。",
        "ko": "얼굴 확인을 실행할 수 없습니다 ({reason}). 그냥 통과시킵니다 — 잠그지 않습니다.",
        "zh": "人脸验证无法运行（{reason}）。已放行——不会锁定电脑。",
        "ru": "Проверку лица не удалось выполнить ({reason}). Пропускаю — блокировки не будет.",
        "ar": "تعذّر تشغيل فحص الوجه ({reason}). سأسمح بالدخول — لن يُقفل الحاسوب.",
        "hi": "चेहरा जाँच नहीं चल सकी ({reason})। आपको जाने दिया जा रहा है — लैपटॉप लॉक नहीं होगा।",
        "tl": "Hindi mapatakbo ang pagsusuri ng mukha ({reason}). Papasaok ka — hindi magla-lock ang laptop.",
        "vi": "Không thể chạy kiểm tra khuôn mặt ({reason}). Vẫn cho bạn vào — máy sẽ không bị khóa.",
        "th": "ตรวจสอบใบหน้าไม่สำเร็จ ({reason}) อนุญาตให้ผ่าน — จะไม่ล็อกเครื่อง",
    },
    "face_locked": {
        "en": "Workstation locked. Sign in with Windows Hello, your PIN or password.",
        "es": "Equipo bloqueado. Inicia sesión con Windows Hello, tu PIN o contraseña.",
        "fr": "Poste verrouillé. Connectez-vous avec Windows Hello, votre code PIN ou mot de passe.",
        "de": "Arbeitsplatz gesperrt. Mit Windows Hello, PIN oder Kennwort anmelden.",
        "it": "Postazione bloccata. Accedi con Windows Hello, il PIN o la password.",
        "pt": "Estação bloqueada. Entre com o Windows Hello, seu PIN ou senha.",
        "ja": "ワークステーションをロックしました。Windows Hello、PIN、またはパスワードでサインインしてください。",
        "ko": "워크스테이션이 잠겼습니다. Windows Hello, PIN 또는 비밀번호로 로그인하세요.",
        "zh": "工作站已锁定。请使用 Windows Hello、PIN 或密码登录。",
        "ru": "Рабочая станция заблокирована. Войдите через Windows Hello, ПИН-код или пароль.",
        "ar": "تم قفل محطة العمل. سجّل الدخول عبر Windows Hello أو رمز PIN أو كلمة المرور.",
        "hi": "वर्कस्टेशन लॉक हो गया। Windows Hello, पिन या पासवर्ड से साइन इन करें।",
        "tl": "Naka-lock ang workstation. Mag-sign in gamit ang Windows Hello, PIN o password.",
        "vi": "Máy đã bị khóa. Hãy đăng nhập bằng Windows Hello, mã PIN hoặc mật khẩu.",
        "th": "ล็อกเวิร์กสเตชันแล้ว กรุณาเข้าสู่ระบบด้วย Windows Hello, PIN หรือรหัสผ่าน",
    },
    "face_override": {
        "en": "Face lock is bypassed for this run ({env}).",
        "es": "El bloqueo facial se omite en esta ejecución ({env}).",
        "fr": "Le verrouillage facial est ignoré pour cette exécution ({env}).",
        "de": "Die Gesichtssperre wird für diesen Lauf umgangen ({env}).",
        "it": "Il blocco facciale è ignorato in questa esecuzione ({env}).",
        "pt": "O bloqueio facial é ignorado nesta execução ({env}).",
        "ja": "この起動では顔ロックをスキップします（{env}）。",
        "ko": "이번 실행에서는 얼굴 잠금을 건너뜁니다({env}).",
        "zh": "本次运行将跳过人脸锁（{env}）。",
        "ru": "Блокировка по лицу пропущена в этом запуске ({env}).",
        "ar": "تم تجاوز قفل الوجه في هذه الجلسة ({env}).",
        "hi": "इस रन में फेस लॉक अनदेखा किया गया ({env})।",
        "tl": "Na-skip ang face lock sa run na ito ({env}).",
        "vi": "Bỏ qua khóa khuôn mặt trong lần chạy này ({env}).",
        "th": "ข้ามการล็อกใบหน้าในการรันครั้งนี้ ({env})",
    },
}


def normalize(code):
    """Map a stored/selected value to a known language code."""
    c = str(code or "en").strip().replace("#", "").lower()
    if c in CODES:
        return c
    for name, lc in LANGUAGES.items():
        if c in (lc, name.strip().lower()):
            return lc
    return "en"


def name_of(code):
    return _NAME_OF.get(normalize(code), "English")


def native_of(code):
    return NATIVE.get(normalize(code), "English")


def t(code, key, **kw):
    """Localized fixed string; falls back to English then the key itself."""
    code = normalize(code)
    table = STRINGS.get(key)
    if not table:
        return key
    text = table.get(code) or table.get("en") or key
    if kw:
        try:
            return text.format(**kw)
        except Exception:
            return text
    return text


def language_directive(code):
    """System-prompt clause pinning the reply language.

    Phrased as an output rule, not a claim about what the user is speaking:
    small local models mirror the input language unless told otherwise, so the
    rule has to name the language and deny the input language any authority.
    """
    code = normalize(code)
    native = native_of(code)
    if code == "en":
        return ("OUTPUT LANGUAGE: English. Write every reply in English, including when "
                "the user writes in another language.")
    return ("OUTPUT LANGUAGE: {native}. Write every single reply in {native} "
            "({name}). This overrides the language of the user's message: if they write "
            "in English or any other language, still answer in {native}. Do not answer "
            "in the language the user used. Keep quoted code, filenames, commands and "
            "proper nouns exactly as written.").format(native=native, name=name_of(code))


def turn_reminder(code):
    """Short per-turn restatement; small local models drift without it."""
    code = normalize(code)
    native = native_of(code)
    if code == "en":
        return "Reply in English."
    return "Reply in {0} only.".format(native)