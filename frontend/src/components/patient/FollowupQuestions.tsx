import { Chip } from "../ui/Chip";
import { t } from "../../lib/i18n";
import type { FollowupAnswer, FollowupQuestion } from "../../types";

type Props = {
  questions: FollowupQuestion[];
  answers: Record<string, string>;
  onAnswer: (id: string, question: string, answer: string) => void;
  language?: string;
};

// Localized placeholder maps for the text-input fallback. The questions
// themselves come from Claude already in the patient's language; only the
// "type a short answer" placeholder needs localization here.
const TEXT_PLACEHOLDER: Record<string, string> = {
  en: "Type a short answer",
  es: "Escribe una respuesta corta",
  zh: "输入简短答案",
  hi: "एक छोटा उत्तर लिखें",
  ar: "اكتب إجابة قصيرة",
  fr: "Tapez une réponse courte",
  pt: "Digite uma resposta curta",
  ru: "Напишите короткий ответ",
  ja: "短い答えを入力",
  ko: "짧은 답을 입력하세요",
  vi: "Nhập câu trả lời ngắn",
  de: "Kurze Antwort eingeben",
  it: "Scrivi una risposta breve",
  tr: "Kısa cevap yazın",
  pl: "Wpisz krótką odpowiedź",
  fa: "یک پاسخ کوتاه بنویسید",
  ur: "ایک مختصر جواب لکھیں",
  id: "Ketik jawaban singkat",
  tl: "Mag-type ng maikling sagot",
  bn: "একটি ছোট উত্তর লিখুন",
};

export function FollowupQuestions({ questions, answers, onAnswer, language = "en" }: Props) {
  const yesLabel = t("form_yes", language);
  const noLabel = t("form_no", language);
  const placeholder = TEXT_PLACEHOLDER[language] || TEXT_PLACEHOLDER.en;
  return (
    <div className="flex flex-col gap-6">
      {questions.map((q) => (
        <div key={q.id} className="flex flex-col gap-3">
          <div className="font-semibold text-lg leading-snug">{q.question}</div>
          {q.type === "boolean" && (
            <div className="flex gap-2">
              {/* Stored answer stays canonical English ("Yes"/"No") so the backend
                  + downstream Claude prompts work uniformly across languages. */}
              <Chip label={yesLabel} selected={answers[q.id] === "Yes"} onToggle={() => onAnswer(q.id, q.question, "Yes")} />
              <Chip label={noLabel} selected={answers[q.id] === "No"} onToggle={() => onAnswer(q.id, q.question, "No")} />
            </div>
          )}
          {q.type === "choice" && (
            <div className="flex flex-wrap gap-2">
              {q.options.map((opt) => (
                <Chip
                  key={opt}
                  label={opt}
                  selected={answers[q.id] === opt}
                  onToggle={() => onAnswer(q.id, q.question, opt)}
                />
              ))}
            </div>
          )}
          {q.type === "text" && (
            <input
              type="text"
              value={answers[q.id] || ""}
              onChange={(e) => onAnswer(q.id, q.question, e.target.value)}
              placeholder={placeholder}
              className="w-full h-12 px-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function toAnswerList(
  questions: FollowupQuestion[],
  answers: Record<string, string>
): FollowupAnswer[] {
  return questions
    .filter((q) => answers[q.id]?.trim())
    .map((q) => ({ id: q.id, question: q.question, answer: answers[q.id] }));
}
