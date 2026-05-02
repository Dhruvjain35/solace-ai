import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Check, Globe } from "lucide-react";
import { LANGUAGES, t, type LangCode } from "../../lib/i18n";

type Props = {
  selected: LangCode;
  onSelect: (code: LangCode) => void;
  onContinue: () => void;
};

/**
 * Language picker as a searchable combobox. Patients can type the name of
 * their language in either English or their native script — the filter is
 * accent / case insensitive and matches both. Replaces the earlier tile grid
 * which scaled badly past ~10 languages on small phones.
 */
export function LanguageGate({ selected, onSelect, onContinue }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Open on focus, close on outside click. Native <select> would be simpler, but
  // it can't show the flag + native script together on most mobile OSes — and
  // patients explicitly need to recognize their language by sight when they
  // can't read English well.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const root = inputRef.current?.parentElement?.parentElement;
      if (!root) return;
      if (!root.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const norm = (s: string) =>
    s
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, ""); // strip diacritics

  const filtered = useMemo(() => {
    const q = norm(query.trim());
    if (!q) return LANGUAGES;
    return LANGUAGES.filter((l) => {
      // Match either the English name, the native name, or the ISO code.
      return (
        norm(l.english).includes(q) ||
        norm(l.native).includes(q) ||
        l.code.toLowerCase().startsWith(q)
      );
    });
  }, [query]);

  // Keep activeIdx in range as the filter narrows.
  useEffect(() => {
    if (activeIdx >= filtered.length) setActiveIdx(0);
  }, [filtered.length, activeIdx]);

  const selectedLang = LANGUAGES.find((l) => l.code === selected);

  function commit(code: LangCode) {
    onSelect(code);
    setQuery("");
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = filtered[activeIdx];
      if (pick) commit(pick.code);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  // Scroll the active option into view whenever it changes.
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.children[activeIdx] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIdx, open]);

  return (
    <div className="flex flex-col gap-6 px-4 py-8 max-w-md w-full mx-auto">
      <div className="text-center">
        <img
          src="/solace-logo.png"
          alt="Solace"
          className="h-16 sm:h-20 w-auto mx-auto select-none"
          draggable={false}
        />
        <h1 className="mt-4 text-2xl sm:text-3xl font-bold tracking-tight">
          {t("language_gate_title", selected)}
        </h1>
        <p className="mt-2 text-text-muted text-sm sm:text-base">
          {t("language_gate_subtitle", selected)}
        </p>
      </div>

      <div className="relative">
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
          />
          <input
            ref={inputRef}
            type="text"
            inputMode="search"
            autoComplete="off"
            value={query}
            placeholder={selectedLang ? `${selectedLang.flag}  ${selectedLang.native}` : "Search…"}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setActiveIdx(0);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            className="w-full h-14 pl-10 pr-12 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
            dir={selectedLang?.rtl ? "rtl" : "ltr"}
          />
          <Globe
            size={16}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
          />
        </div>

        <AnimatePresence>
          {open && (
            <motion.ul
              ref={listRef}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.12 }}
              role="listbox"
              className="absolute left-0 right-0 top-full mt-1.5 max-h-[280px] overflow-y-auto rounded-md bg-surface-lowest shadow-card ring-1 ring-line z-10"
            >
              {filtered.length === 0 ? (
                <li className="px-3 py-3 text-sm text-text-muted text-center">
                  No matching language.
                </li>
              ) : (
                filtered.map((lang, i) => {
                  const isActive = i === activeIdx;
                  const isSelected = lang.code === selected;
                  return (
                    <li
                      key={lang.code}
                      role="option"
                      aria-selected={isSelected}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        commit(lang.code);
                      }}
                      onMouseEnter={() => setActiveIdx(i)}
                      className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer ${
                        isActive ? "bg-primary-fixed" : ""
                      }`}
                      dir={lang.rtl ? "rtl" : "ltr"}
                    >
                      <span className="text-xl leading-none" aria-hidden>
                        {lang.flag}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold leading-tight truncate">
                          {lang.native}
                        </div>
                        <div className="text-[11px] text-text-muted leading-tight">
                          {lang.english}
                        </div>
                      </div>
                      {isSelected && <Check size={14} className="text-primary shrink-0" />}
                    </li>
                  );
                })
              )}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>

      <button
        type="button"
        onClick={onContinue}
        className="h-14 rounded-md bg-primary text-white font-semibold text-base shadow-soft hover:bg-primary-hover transition-colors"
      >
        {t("continue_button", selected)} →
      </button>

      <p className="text-[11px] text-text-muted text-center">
        {LANGUAGES.length} languages · type to search
      </p>
    </div>
  );
}
