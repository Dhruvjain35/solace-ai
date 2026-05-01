import { motion } from "framer-motion";
import { LANGUAGES, t, type LangCode } from "../../lib/i18n";

type Props = {
  selected: LangCode;
  onSelect: (code: LangCode) => void;
  onContinue: () => void;
};

export function LanguageGate({ selected, onSelect, onContinue }: Props) {
  return (
    <div className="flex flex-col gap-6 px-4 py-8 max-w-2xl w-full mx-auto">
      <div className="text-center">
        <img
          src="/solace-logo.png"
          alt="Solace"
          className="h-16 sm:h-20 w-auto mx-auto select-none"
          draggable={false}
        />
        <h1 className="mt-4 text-2xl sm:text-3xl font-bold tracking-editorial-tight">
          {t("language_gate_title", selected)}
        </h1>
        <p className="mt-2 text-text-muted text-sm sm:text-base">
          {t("language_gate_subtitle", selected)}
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
        {LANGUAGES.map((lang) => {
          const isActive = lang.code === selected;
          return (
            <motion.button
              key={lang.code}
              type="button"
              onClick={() => onSelect(lang.code)}
              whileTap={{ scale: 0.97 }}
              className={`flex flex-col items-center justify-center gap-1 rounded-lg border-2 p-3 transition-all ${
                isActive
                  ? "border-primary bg-primary-fixed/60 shadow-soft"
                  : "border-line bg-surface-lowest hover:border-primary/40"
              }`}
              dir={lang.rtl ? "rtl" : "ltr"}
            >
              <span className="text-2xl leading-none" aria-hidden>
                {lang.flag}
              </span>
              <span className="text-base font-semibold tracking-editorial leading-tight">
                {lang.native}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-text-muted">
                {lang.english}
              </span>
            </motion.button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={onContinue}
        className="h-14 rounded-md bg-primary text-white font-semibold text-base shadow-soft hover:bg-primary-hover transition-colors"
      >
        {t("continue_button", selected)} →
      </button>
    </div>
  );
}
