// Lightweight i18n for the patient intake flow. No library — keeps the bundle small.
// Languages chosen to cover both Whisper STT (whisper-1) and ElevenLabs multilingual_v2.

export type LangCode =
  | "en" | "es" | "zh" | "hi" | "ar" | "fr" | "pt" | "ru" | "ja" | "ko"
  | "vi" | "de" | "it" | "tr" | "pl" | "fa" | "ur" | "id" | "tl" | "bn";

export type LanguageOption = {
  code: LangCode;
  english: string;   // "Spanish"
  native: string;    // "Español"
  flag: string;      // unicode flag/region marker (single grapheme, fine for tile UI)
  rtl?: boolean;
};

export const LANGUAGES: LanguageOption[] = [
  { code: "en", english: "English",    native: "English",       flag: "🇺🇸" },
  { code: "es", english: "Spanish",    native: "Español",       flag: "🇪🇸" },
  { code: "zh", english: "Chinese",    native: "中文",          flag: "🇨🇳" },
  { code: "hi", english: "Hindi",      native: "हिन्दी",          flag: "🇮🇳" },
  { code: "ar", english: "Arabic",     native: "العربية",        flag: "🇸🇦", rtl: true },
  { code: "fr", english: "French",     native: "Français",      flag: "🇫🇷" },
  { code: "pt", english: "Portuguese", native: "Português",     flag: "🇧🇷" },
  { code: "ru", english: "Russian",    native: "Русский",       flag: "🇷🇺" },
  { code: "ja", english: "Japanese",   native: "日本語",         flag: "🇯🇵" },
  { code: "ko", english: "Korean",     native: "한국어",         flag: "🇰🇷" },
  { code: "vi", english: "Vietnamese", native: "Tiếng Việt",    flag: "🇻🇳" },
  { code: "de", english: "German",     native: "Deutsch",       flag: "🇩🇪" },
  { code: "it", english: "Italian",    native: "Italiano",      flag: "🇮🇹" },
  { code: "tr", english: "Turkish",    native: "Türkçe",        flag: "🇹🇷" },
  { code: "pl", english: "Polish",     native: "Polski",        flag: "🇵🇱" },
  { code: "fa", english: "Persian",    native: "فارسی",          flag: "🇮🇷", rtl: true },
  { code: "ur", english: "Urdu",       native: "اردو",           flag: "🇵🇰", rtl: true },
  { code: "id", english: "Indonesian", native: "Bahasa Indonesia", flag: "🇮🇩" },
  { code: "tl", english: "Filipino",   native: "Filipino",      flag: "🇵🇭" },
  { code: "bn", english: "Bengali",    native: "বাংলা",         flag: "🇧🇩" },
];

export function isRTL(lang: string): boolean {
  return LANGUAGES.find((l) => l.code === lang)?.rtl === true;
}

// Translation keys used across the patient intake. Missing translations fall back to English.
type Key =
  | "welcome_title"
  | "welcome_subtitle"
  | "first_name_label"
  | "first_name_placeholder"
  | "consent_lead"
  | "consent_body"
  | "consent_decline"
  | "medical_title"
  | "medical_subtitle"
  | "insurance_title"
  | "insurance_subtitle"
  | "record_title"
  | "record_subtitle_voice"
  | "record_subtitle_type"
  | "record_voice_tab"
  | "record_type_tab"
  | "record_textarea_placeholder"
  | "record_mic_denied"
  | "record_captured"
  | "record_rerecord"
  | "followups_title"
  | "followups_subtitle"
  | "submit_button"
  | "next_button"
  | "continue_button"
  | "back_button"
  | "working_button"
  | "submitting_title"
  | "submitting_subtitle"
  | "footer_disclaimer"
  | "language_gate_title"
  | "language_gate_subtitle"
  | "error_transcription_down"
  | "error_rate_limited"
  | "error_network"
  | "error_generic"
  | "we_speak_back";

type Dict = Partial<Record<Key, string>>;

const en: Record<Key, string> = {
  welcome_title: "You're not waiting alone.",
  welcome_subtitle: "Tell us your story once. By the time a clinician sees you, they'll already know.",
  first_name_label: "Your first name",
  first_name_placeholder: "Marcus",
  consent_lead: "I consent to AI processing.",
  consent_body:
    "My voice recording, symptoms, and any photos I upload will be sent to third-party AI services (OpenAI for voice transcription, Anthropic for triage and scribe notes, ElevenLabs for the audio response). Each visit appends an attribution log so the clinician sees exactly which provider saw which data.",
  consent_decline:
    "Decline by refreshing the page and asking a front-desk worker to collect your info manually.",
  medical_title: "A few medical details",
  medical_subtitle: "So the clinician doesn't have to ask later.",
  insurance_title: "Insurance (optional)",
  insurance_subtitle: "Snap a picture and we'll auto-fill the details. You can also skip this.",
  record_title: "What's going on?",
  record_subtitle_voice: "Speak naturally for 20-60 seconds. Or type if it's loud.",
  record_subtitle_type: "Write what's happening. A few sentences is enough.",
  record_voice_tab: "Voice",
  record_type_tab: "Type",
  record_textarea_placeholder:
    "Describe your symptoms — what hurts, when it started, how bad it feels, anything else going on.",
  record_mic_denied: "Mic access was denied.",
  record_captured: "Recording captured",
  record_rerecord: "re-record",
  followups_title: "A few quick questions",
  followups_subtitle: "These help us give your clinician a complete picture.",
  submit_button: "Submit",
  next_button: "Next",
  continue_button: "Continue",
  back_button: "Back",
  working_button: "Working…",
  submitting_title: "Finalizing your assessment…",
  submitting_subtitle: "Generating your pre-brief for the clinician.",
  footer_disclaimer:
    "Triage aid only. Clinicians always verify. If life-threatening, go to the front desk now.",
  language_gate_title: "Choose your language",
  language_gate_subtitle: "We'll guide your check-in in this language.",
  error_transcription_down:
    "Voice transcription is temporarily unavailable — please type your symptoms below and tap Next again.",
  error_rate_limited:
    "We're handling a lot of patients right now. Please wait a moment and tap Next again.",
  error_network:
    "Connection hiccup — please check your signal and tap Next again. Your inputs are saved.",
  error_generic: "Something went wrong. Please try again.",
  we_speak_back:
    "We'll transcribe your voice and speak the comfort protocol back in this language.",
};

// Translations are intentionally hand-written for the most common patient phrases.
// Missing keys fall back to English. Free to extend incrementally without breaking anything.
const dictionaries: Record<string, Dict> = {
  en,
  es: {
    welcome_title: "No estás esperando solo.",
    welcome_subtitle:
      "Cuéntanos tu historia una vez. Cuando te vea un médico, ya la conocerá.",
    first_name_label: "Tu nombre",
    first_name_placeholder: "Marcos",
    consent_lead: "Doy mi consentimiento para el procesamiento por IA.",
    consent_body:
      "Mi grabación de voz, síntomas y fotos se enviarán a servicios de IA de terceros (OpenAI para transcripción, Anthropic para triaje, ElevenLabs para audio). Cada visita registra qué proveedor vio qué datos.",
    consent_decline:
      "Rechaza recargando la página y pidiendo a la recepción que recoja tus datos manualmente.",
    medical_title: "Algunos datos médicos",
    medical_subtitle: "Para que el médico no tenga que preguntar después.",
    insurance_title: "Seguro (opcional)",
    insurance_subtitle:
      "Toma una foto y rellenaremos los datos. También puedes omitir este paso.",
    record_title: "¿Qué pasa?",
    record_subtitle_voice: "Habla con naturalidad 20-60 segundos. O escribe si hay ruido.",
    record_subtitle_type: "Escribe lo que sucede. Unas frases bastan.",
    record_voice_tab: "Voz",
    record_type_tab: "Escribir",
    record_textarea_placeholder:
      "Describe tus síntomas — qué te duele, cuándo empezó, qué tan fuerte, y cualquier otra cosa.",
    record_mic_denied: "Acceso al micrófono denegado.",
    record_captured: "Grabación capturada",
    record_rerecord: "regrabar",
    followups_title: "Unas preguntas rápidas",
    followups_subtitle: "Esto nos ayuda a darle al médico una imagen completa.",
    submit_button: "Enviar",
    next_button: "Siguiente",
    continue_button: "Continuar",
    back_button: "Atrás",
    working_button: "Procesando…",
    submitting_title: "Finalizando tu evaluación…",
    submitting_subtitle: "Generando el resumen para el médico.",
    footer_disclaimer:
      "Solo apoyo al triaje. Los médicos siempre verifican. Si es urgente, ve a recepción ahora.",
    language_gate_title: "Elige tu idioma",
    language_gate_subtitle: "Te guiaremos en este idioma.",
    error_transcription_down:
      "La transcripción de voz no está disponible — por favor escribe tus síntomas y toca Siguiente.",
    error_rate_limited:
      "Estamos atendiendo muchas personas. Espera un momento y toca Siguiente otra vez.",
    error_network:
      "Problema de conexión — revisa la señal y vuelve a tocar Siguiente. Tus datos están guardados.",
    error_generic: "Algo salió mal. Inténtalo de nuevo.",
    we_speak_back:
      "Transcribiremos tu voz y diremos el protocolo de bienestar en este idioma.",
  },
  zh: {
    welcome_title: "您不是一个人在等待。",
    welcome_subtitle: "把您的情况告诉我们一次。临床医生见到您时已经了解情况。",
    first_name_label: "您的名字",
    first_name_placeholder: "李明",
    consent_lead: "我同意 AI 处理。",
    consent_body:
      "我的录音、症状和照片将发送到第三方 AI 服务（OpenAI 转录,Anthropic 分诊,ElevenLabs 语音）。每次就诊都会记录哪个提供商看到了哪些数据。",
    consent_decline: "拒绝请刷新页面并请前台手动收集您的信息。",
    medical_title: "一些医疗信息",
    medical_subtitle: "这样医生就不必再问。",
    insurance_title: "保险(可选)",
    insurance_subtitle: "拍照后我们会自动填写。您也可以跳过。",
    record_title: "怎么了?",
    record_subtitle_voice: "自然说话 20-60 秒。如果太吵也可以打字。",
    record_subtitle_type: "写下情况。几句话就够了。",
    record_voice_tab: "语音",
    record_type_tab: "打字",
    record_textarea_placeholder: "描述您的症状 — 哪里疼,何时开始,有多严重,还有什么。",
    record_mic_denied: "麦克风权限被拒绝。",
    record_captured: "已录制",
    record_rerecord: "重录",
    followups_title: "几个快速问题",
    followups_subtitle: "帮助我们为医生提供完整信息。",
    submit_button: "提交",
    next_button: "下一步",
    continue_button: "继续",
    back_button: "返回",
    working_button: "处理中…",
    submitting_title: "正在完成评估…",
    submitting_subtitle: "正在为医生生成预报告。",
    footer_disclaimer: "仅辅助分诊。医生始终复核。如有生命危险,请立即前往前台。",
    language_gate_title: "选择您的语言",
    language_gate_subtitle: "我们将以此语言引导您。",
    error_transcription_down: "语音转录暂时不可用 — 请输入症状并再次点击下一步。",
    error_rate_limited: "我们正在处理许多患者。请稍候再点击下一步。",
    error_network: "网络问题 — 请检查信号后再次点击下一步。您的输入已保存。",
    error_generic: "出错了,请重试。",
    we_speak_back: "我们会用此语言转录您的声音并播放安抚指引。",
  },
  hi: {
    welcome_title: "आप अकेले इंतज़ार नहीं कर रहे।",
    welcome_subtitle: "एक बार बताएं — जब डॉक्टर मिलेंगे, उन्हें पहले से पता होगा।",
    first_name_label: "आपका पहला नाम",
    first_name_placeholder: "आरव",
    consent_lead: "मैं AI प्रोसेसिंग के लिए सहमति देता/देती हूँ।",
    consent_body:
      "मेरी आवाज़, लक्षण और तस्वीरें थर्ड-पार्टी AI सेवाओं को भेजी जाएंगी (OpenAI ट्रांसक्रिप्शन, Anthropic ट्राइएज, ElevenLabs ऑडियो)।",
    consent_decline: "मना करने के लिए पेज रिफ्रेश करें और रिसेप्शन से मैनुअल जानकारी लेने को कहें।",
    medical_title: "कुछ मेडिकल जानकारी",
    medical_subtitle: "ताकि डॉक्टर बाद में न पूछें।",
    insurance_title: "बीमा (वैकल्पिक)",
    insurance_subtitle: "फोटो लें — हम विवरण भर देंगे। आप छोड़ भी सकते हैं।",
    record_title: "क्या हो रहा है?",
    record_subtitle_voice: "20-60 सेकंड स्वाभाविक रूप से बोलें। शोर हो तो टाइप करें।",
    record_subtitle_type: "जो हो रहा है लिखें। कुछ वाक्य काफी हैं।",
    record_voice_tab: "आवाज़",
    record_type_tab: "टाइप",
    record_textarea_placeholder: "लक्षण बताएं — कहाँ दर्द है, कब शुरू हुआ, कितना तेज़।",
    record_mic_denied: "माइक एक्सेस अस्वीकृत।",
    record_captured: "रिकॉर्डिंग पूरी",
    record_rerecord: "फिर से रिकॉर्ड करें",
    followups_title: "कुछ त्वरित प्रश्न",
    followups_subtitle: "ये डॉक्टर को पूरी जानकारी देने में मदद करते हैं।",
    submit_button: "भेजें",
    next_button: "आगे",
    continue_button: "जारी रखें",
    back_button: "वापस",
    working_button: "प्रोसेसिंग…",
    submitting_title: "मूल्यांकन पूरा हो रहा है…",
    submitting_subtitle: "डॉक्टर के लिए सारांश तैयार हो रहा है।",
    footer_disclaimer: "केवल ट्राइएज सहायक। डॉक्टर हमेशा सत्यापित करते हैं।",
    language_gate_title: "अपनी भाषा चुनें",
    language_gate_subtitle: "हम इसी भाषा में मार्गदर्शन करेंगे।",
    error_transcription_down: "वॉयस ट्रांसक्रिप्शन उपलब्ध नहीं — कृपया लक्षण टाइप करें।",
    error_rate_limited: "हम कई मरीज़ों की मदद कर रहे हैं। थोड़ी देर बाद आगे दबाएं।",
    error_network: "कनेक्शन समस्या — सिग्नल जांचें और फिर से आगे दबाएं।",
    error_generic: "कुछ गलत हुआ। कृपया पुनः प्रयास करें।",
    we_speak_back: "हम आपकी आवाज़ ट्रांसक्राइब करेंगे और इसी भाषा में जवाब देंगे।",
  },
  ar: {
    welcome_title: "لست تنتظر وحدك.",
    welcome_subtitle: "أخبرنا قصتك مرة واحدة — عندما يراك الطبيب سيكون عارفاً.",
    first_name_label: "اسمك الأول",
    first_name_placeholder: "أحمد",
    consent_lead: "أوافق على معالجة الذكاء الاصطناعي.",
    consent_body:
      "سيتم إرسال صوتي وأعراضي وصوري إلى خدمات ذكاء اصطناعي تابعة لجهات خارجية (OpenAI، Anthropic، ElevenLabs).",
    consent_decline: "للرفض، أعد تحميل الصفحة واطلب من الاستقبال جمع البيانات يدوياً.",
    medical_title: "بعض التفاصيل الطبية",
    medical_subtitle: "حتى لا يسأل الطبيب لاحقاً.",
    insurance_title: "التأمين (اختياري)",
    insurance_subtitle: "التقط صورة وسنملأ التفاصيل. يمكنك التخطي أيضاً.",
    record_title: "ما الذي يحدث؟",
    record_subtitle_voice: "تحدث 20-60 ثانية. أو اكتب إن كان الجو ضوضاء.",
    record_subtitle_type: "اكتب ما يحدث. جمل قليلة كافية.",
    record_voice_tab: "صوت",
    record_type_tab: "كتابة",
    record_textarea_placeholder: "صف الأعراض — أين الألم، متى بدأ، شدته.",
    record_mic_denied: "تم رفض الوصول إلى الميكروفون.",
    record_captured: "تم التسجيل",
    record_rerecord: "إعادة التسجيل",
    followups_title: "أسئلة سريعة",
    followups_subtitle: "تساعدنا في إعطاء الطبيب صورة كاملة.",
    submit_button: "إرسال",
    next_button: "التالي",
    continue_button: "متابعة",
    back_button: "رجوع",
    working_button: "جارٍ المعالجة…",
    submitting_title: "إنهاء التقييم…",
    submitting_subtitle: "إنشاء ملخص للطبيب.",
    footer_disclaimer: "للمساعدة في الفرز فقط. الأطباء يتحققون دائماً.",
    language_gate_title: "اختر لغتك",
    language_gate_subtitle: "سنرشدك بهذه اللغة.",
    error_transcription_down: "خدمة النسخ الصوتي غير متاحة — اكتب الأعراض رجاءً.",
    error_rate_limited: "نحن نخدم عدداً كبيراً. انتظر لحظة ثم اضغط التالي.",
    error_network: "مشكلة اتصال — تحقق من الإشارة واضغط التالي.",
    error_generic: "حدث خطأ. حاول مرة أخرى.",
    we_speak_back: "سننسخ صوتك ونرد بهذه اللغة.",
  },
  fr: {
    welcome_title: "Vous n'attendez pas seul·e.",
    welcome_subtitle:
      "Racontez-nous votre histoire une fois. Quand le clinicien vous verra, il saura déjà.",
    first_name_label: "Votre prénom",
    first_name_placeholder: "Marcus",
    consent_lead: "Je consens au traitement par IA.",
    consent_body:
      "Mon enregistrement, mes symptômes et mes photos seront envoyés à des services IA tiers (OpenAI, Anthropic, ElevenLabs).",
    consent_decline:
      "Pour refuser, rafraîchissez la page et demandez à l'accueil de saisir vos infos.",
    medical_title: "Quelques détails médicaux",
    medical_subtitle: "Pour que le clinicien n'ait pas à demander.",
    insurance_title: "Assurance (facultatif)",
    insurance_subtitle: "Photographiez et nous remplirons. Vous pouvez aussi passer.",
    record_title: "Que se passe-t-il ?",
    record_subtitle_voice: "Parlez naturellement 20-60 secondes. Ou tapez si bruyant.",
    record_subtitle_type: "Écrivez ce qui arrive. Quelques phrases suffisent.",
    record_voice_tab: "Voix",
    record_type_tab: "Texte",
    record_textarea_placeholder: "Décrivez les symptômes — où, depuis quand, intensité.",
    record_mic_denied: "Accès au micro refusé.",
    record_captured: "Enregistrement capturé",
    record_rerecord: "réenregistrer",
    followups_title: "Quelques questions",
    followups_subtitle: "Pour donner au clinicien une image complète.",
    submit_button: "Envoyer",
    next_button: "Suivant",
    continue_button: "Continuer",
    back_button: "Retour",
    working_button: "Traitement…",
    submitting_title: "Finalisation de l'évaluation…",
    submitting_subtitle: "Génération du résumé pour le clinicien.",
    footer_disclaimer: "Aide au triage uniquement. Les cliniciens vérifient toujours.",
    language_gate_title: "Choisissez votre langue",
    language_gate_subtitle: "Nous vous guiderons dans cette langue.",
    error_transcription_down:
      "Transcription vocale indisponible — tapez vos symptômes et appuyez sur Suivant.",
    error_rate_limited: "Beaucoup de patients en cours. Attendez un instant.",
    error_network: "Souci de connexion — vérifiez et appuyez à nouveau.",
    error_generic: "Une erreur est survenue. Réessayez.",
    we_speak_back: "Nous transcrivons votre voix et répondons dans cette langue.",
  },
  pt: {
    welcome_title: "Você não está esperando sozinho.",
    welcome_subtitle: "Conte-nos sua história uma vez. Quando o clínico vir você, já saberá.",
    first_name_label: "Seu primeiro nome",
    first_name_placeholder: "Marcos",
    consent_lead: "Eu consinto com o processamento por IA.",
    consent_body:
      "Minha gravação, sintomas e fotos serão enviados a serviços de IA terceiros (OpenAI, Anthropic, ElevenLabs).",
    consent_decline: "Para recusar, atualize a página e peça à recepção para coletar manualmente.",
    medical_title: "Alguns dados médicos",
    medical_subtitle: "Para que o clínico não precise perguntar depois.",
    insurance_title: "Plano de saúde (opcional)",
    insurance_subtitle: "Tire uma foto e preencheremos. Pode pular também.",
    record_title: "O que está acontecendo?",
    record_subtitle_voice: "Fale naturalmente por 20-60 segundos. Ou digite se houver barulho.",
    record_subtitle_type: "Escreva o que acontece. Algumas frases bastam.",
    record_voice_tab: "Voz",
    record_type_tab: "Texto",
    record_textarea_placeholder: "Descreva os sintomas — onde, há quanto tempo, intensidade.",
    record_mic_denied: "Acesso ao microfone negado.",
    record_captured: "Gravação capturada",
    record_rerecord: "regravar",
    followups_title: "Algumas perguntas rápidas",
    followups_subtitle: "Para dar ao clínico uma imagem completa.",
    submit_button: "Enviar",
    next_button: "Próximo",
    continue_button: "Continuar",
    back_button: "Voltar",
    working_button: "Processando…",
    submitting_title: "Finalizando sua avaliação…",
    submitting_subtitle: "Gerando o resumo para o clínico.",
    footer_disclaimer: "Apenas auxílio à triagem. Clínicos sempre verificam.",
    language_gate_title: "Escolha seu idioma",
    language_gate_subtitle: "Vamos guiar nesse idioma.",
    error_transcription_down: "Transcrição indisponível — digite os sintomas e toque em Próximo.",
    error_rate_limited: "Atendendo muitos pacientes. Aguarde um momento.",
    error_network: "Problema de conexão — verifique o sinal e toque em Próximo.",
    error_generic: "Algo deu errado. Tente novamente.",
    we_speak_back: "Transcreveremos sua voz e falaremos neste idioma.",
  },
  ru: {
    welcome_title: "Вы ждёте не одни.",
    welcome_subtitle: "Расскажите нам один раз — врач уже будет знать.",
    first_name_label: "Ваше имя",
    first_name_placeholder: "Иван",
    consent_lead: "Согласие на обработку ИИ.",
    consent_body:
      "Запись, симптомы и фото будут отправлены сторонним сервисам ИИ (OpenAI, Anthropic, ElevenLabs).",
    consent_decline: "Чтобы отказаться, обновите страницу и обратитесь на ресепшн.",
    medical_title: "Медицинская информация",
    medical_subtitle: "Чтобы врач не спрашивал позже.",
    insurance_title: "Страховка (необязательно)",
    insurance_subtitle: "Сфотографируйте — мы заполним. Можно пропустить.",
    record_title: "Что случилось?",
    record_subtitle_voice: "Говорите 20-60 секунд. Или напечатайте, если шумно.",
    record_subtitle_type: "Опишите ситуацию. Несколько предложений достаточно.",
    record_voice_tab: "Голос",
    record_type_tab: "Текст",
    record_textarea_placeholder: "Опишите симптомы — где болит, когда началось, насколько сильно.",
    record_mic_denied: "Доступ к микрофону отклонён.",
    record_captured: "Запись готова",
    record_rerecord: "перезаписать",
    followups_title: "Быстрые вопросы",
    followups_subtitle: "Помогут дать врачу полную картину.",
    submit_button: "Отправить",
    next_button: "Далее",
    continue_button: "Продолжить",
    back_button: "Назад",
    working_button: "Обработка…",
    submitting_title: "Завершаем оценку…",
    submitting_subtitle: "Готовим сводку для врача.",
    footer_disclaimer: "Только сортировка. Врачи всегда проверяют.",
    language_gate_title: "Выберите язык",
    language_gate_subtitle: "Будем вести вас на этом языке.",
    error_transcription_down: "Транскрипция недоступна — напечатайте симптомы.",
    error_rate_limited: "Сейчас много пациентов. Подождите и нажмите Далее.",
    error_network: "Проблема со связью — проверьте сигнал и нажмите снова.",
    error_generic: "Что-то пошло не так. Попробуйте снова.",
    we_speak_back: "Мы транскрибируем голос и ответим на этом языке.",
  },
  ja: {
    welcome_title: "一人で待たないで。",
    welcome_subtitle: "一度だけお話しください。医師が来た時には既に把握しています。",
    first_name_label: "お名前",
    first_name_placeholder: "太郎",
    consent_lead: "AI 処理に同意します。",
    consent_body:
      "音声・症状・写真は第三者 AI サービス(OpenAI, Anthropic, ElevenLabs)に送信されます。",
    consent_decline: "拒否するには、ページを更新し受付に手動入力を依頼してください。",
    medical_title: "医療情報",
    medical_subtitle: "医師が後で聞かなくて済むように。",
    insurance_title: "保険 (任意)",
    insurance_subtitle: "写真を撮ると自動入力します。スキップも可能。",
    record_title: "どうされましたか?",
    record_subtitle_voice: "20-60秒、自然に話してください。騒がしければ入力でも。",
    record_subtitle_type: "状況を書いてください。数文で十分です。",
    record_voice_tab: "音声",
    record_type_tab: "入力",
    record_textarea_placeholder: "症状を説明してください — 痛む場所、いつから、強さ。",
    record_mic_denied: "マイクが拒否されました。",
    record_captured: "録音完了",
    record_rerecord: "録音し直す",
    followups_title: "簡単な質問",
    followups_subtitle: "医師に全体像を渡すのに役立ちます。",
    submit_button: "送信",
    next_button: "次へ",
    continue_button: "続ける",
    back_button: "戻る",
    working_button: "処理中…",
    submitting_title: "評価を完了中…",
    submitting_subtitle: "医師向け要約を生成中。",
    footer_disclaimer: "トリアージ補助のみ。医師は常に確認します。",
    language_gate_title: "言語を選択",
    language_gate_subtitle: "この言語でご案内します。",
    error_transcription_down: "音声転写は利用できません — 症状を入力してください。",
    error_rate_limited: "多数の患者対応中です。少し待って次へを押してください。",
    error_network: "接続不良 — 信号を確認して再度押してください。",
    error_generic: "問題が発生しました。再試行してください。",
    we_speak_back: "音声を転写し、この言語で返答します。",
  },
  ko: {
    welcome_title: "혼자 기다리지 않으세요.",
    welcome_subtitle: "한 번만 말씀해 주세요. 의사가 만날 때 이미 알고 있을 거예요.",
    first_name_label: "이름",
    first_name_placeholder: "민수",
    consent_lead: "AI 처리에 동의합니다.",
    consent_body:
      "음성·증상·사진은 제3자 AI 서비스(OpenAI, Anthropic, ElevenLabs)로 전송됩니다.",
    consent_decline: "거부하려면 페이지를 새로 고치고 접수처에 수동 입력을 요청하세요.",
    medical_title: "몇 가지 의료 정보",
    medical_subtitle: "의사가 나중에 묻지 않도록.",
    insurance_title: "보험 (선택)",
    insurance_subtitle: "사진을 찍으면 자동 입력합니다. 건너뛸 수도 있어요.",
    record_title: "무슨 일인가요?",
    record_subtitle_voice: "20-60초 자연스럽게 말씀하세요. 시끄럽다면 입력도 가능.",
    record_subtitle_type: "상황을 적어주세요. 몇 문장이면 충분해요.",
    record_voice_tab: "음성",
    record_type_tab: "입력",
    record_textarea_placeholder: "증상 설명 — 어디가 아프고, 언제 시작했고, 얼마나 심한지.",
    record_mic_denied: "마이크 액세스가 거부되었습니다.",
    record_captured: "녹음 완료",
    record_rerecord: "다시 녹음",
    followups_title: "간단한 질문",
    followups_subtitle: "의사에게 전체 그림을 전하는 데 도움.",
    submit_button: "제출",
    next_button: "다음",
    continue_button: "계속",
    back_button: "뒤로",
    working_button: "처리 중…",
    submitting_title: "평가 마무리 중…",
    submitting_subtitle: "의사용 요약 생성 중.",
    footer_disclaimer: "분류 보조용. 의사는 항상 확인합니다.",
    language_gate_title: "언어를 선택하세요",
    language_gate_subtitle: "이 언어로 안내합니다.",
    error_transcription_down: "음성 전사 불가 — 증상을 입력하세요.",
    error_rate_limited: "많은 환자를 보고 있어요. 잠시 후 다시 누르세요.",
    error_network: "연결 문제 — 신호를 확인하고 다시 누르세요.",
    error_generic: "문제가 발생했어요. 다시 시도하세요.",
    we_speak_back: "음성을 전사하고 이 언어로 답합니다.",
  },
  vi: {
    welcome_title: "Bạn không chờ một mình.",
    welcome_subtitle: "Kể chúng tôi một lần. Khi bác sĩ gặp bạn, họ đã biết.",
    first_name_label: "Tên của bạn",
    first_name_placeholder: "An",
    consent_lead: "Tôi đồng ý xử lý AI.",
    consent_body:
      "Ghi âm, triệu chứng và ảnh sẽ được gửi đến dịch vụ AI bên thứ ba (OpenAI, Anthropic, ElevenLabs).",
    consent_decline: "Để từ chối, làm mới trang và yêu cầu lễ tân nhập thủ công.",
    medical_title: "Một vài chi tiết y tế",
    medical_subtitle: "Để bác sĩ không phải hỏi lại.",
    insurance_title: "Bảo hiểm (tùy chọn)",
    insurance_subtitle: "Chụp ảnh và chúng tôi sẽ điền. Cũng có thể bỏ qua.",
    record_title: "Chuyện gì vậy?",
    record_subtitle_voice: "Nói tự nhiên 20-60 giây. Hoặc gõ nếu ồn.",
    record_subtitle_type: "Viết chuyện đang xảy ra. Vài câu là đủ.",
    record_voice_tab: "Giọng nói",
    record_type_tab: "Gõ",
    record_textarea_placeholder: "Mô tả triệu chứng — đau ở đâu, khi nào, mức độ.",
    record_mic_denied: "Quyền truy cập mic bị từ chối.",
    record_captured: "Đã ghi âm",
    record_rerecord: "ghi lại",
    followups_title: "Vài câu hỏi nhanh",
    followups_subtitle: "Giúp đưa bức tranh đầy đủ cho bác sĩ.",
    submit_button: "Gửi",
    next_button: "Tiếp",
    continue_button: "Tiếp tục",
    back_button: "Quay lại",
    working_button: "Đang xử lý…",
    submitting_title: "Hoàn tất đánh giá…",
    submitting_subtitle: "Tạo bản tóm tắt cho bác sĩ.",
    footer_disclaimer: "Chỉ hỗ trợ phân loại. Bác sĩ luôn xác minh.",
    language_gate_title: "Chọn ngôn ngữ",
    language_gate_subtitle: "Chúng tôi sẽ hướng dẫn bằng ngôn ngữ này.",
    error_transcription_down: "Phiên âm không khả dụng — vui lòng gõ triệu chứng.",
    error_rate_limited: "Đang phục vụ nhiều bệnh nhân. Đợi một lát rồi nhấn Tiếp.",
    error_network: "Sự cố kết nối — kiểm tra tín hiệu và nhấn lại.",
    error_generic: "Có lỗi xảy ra. Vui lòng thử lại.",
    we_speak_back: "Chúng tôi phiên âm và trả lời bằng ngôn ngữ này.",
  },
  // Languages below fall back to English for now — the picker still shows native names,
  // and Whisper/ElevenLabs handle the speech path in their native language anyway.
  de: {},
  it: {},
  tr: {},
  pl: {},
  fa: {},
  ur: {},
  id: {},
  tl: {},
  bn: {},
};

export function t(key: Key, lang: string): string {
  const dict = dictionaries[lang];
  if (dict && dict[key]) return dict[key]!;
  return en[key];
}
