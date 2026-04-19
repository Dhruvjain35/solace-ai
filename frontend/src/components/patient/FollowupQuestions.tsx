import { Chip } from "../ui/Chip";
import type { FollowupAnswer, FollowupQuestion } from "../../types";

type Props = {
  questions: FollowupQuestion[];
  answers: Record<string, string>;
  onAnswer: (id: string, question: string, answer: string) => void;
};

export function FollowupQuestions({ questions, answers, onAnswer }: Props) {
  return (
    <div className="flex flex-col gap-6">
      {questions.map((q) => (
        <div key={q.id} className="flex flex-col gap-3">
          <div className="font-semibold text-lg leading-snug">{q.question}</div>
          {q.type === "boolean" && (
            <div className="flex gap-2">
              <Chip label="Yes" selected={answers[q.id] === "Yes"} onToggle={() => onAnswer(q.id, q.question, "Yes")} />
              <Chip label="No" selected={answers[q.id] === "No"} onToggle={() => onAnswer(q.id, q.question, "No")} />
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
              placeholder="Type a short answer"
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
