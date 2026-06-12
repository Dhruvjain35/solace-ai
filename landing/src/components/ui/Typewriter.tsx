import { useEffect, useState } from 'react';
import { useReducedMotion } from 'framer-motion';

// Cycling typewriter — types a word, holds, deletes, moves to the next.
// Mirrors the cruisenow.ai hero ("Charts." -> "Docs." ...).
export default function Typewriter({
  words,
  className = '',
}: {
  words: string[];
  className?: string;
}) {
  const reduce = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [text, setText] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (reduce) {
      setText(words[0]);
      return;
    }
    const full = words[index % words.length];
    const done = text === full;
    const empty = text === '';

    let delay = deleting ? 45 : 90;
    if (done && !deleting) delay = 1600; // hold at full word
    if (empty && deleting) delay = 350;

    const timer = setTimeout(() => {
      if (!deleting && done) {
        setDeleting(true);
      } else if (deleting && empty) {
        setDeleting(false);
        setIndex((i) => (i + 1) % words.length);
      } else {
        setText(full.slice(0, text.length + (deleting ? -1 : 1)));
      }
    }, delay);

    return () => clearTimeout(timer);
  }, [text, deleting, index, words, reduce]);

  return (
    <span className={className}>
      {text}
      <span className="ml-1 inline-block w-[0.06em] -translate-y-[0.05em] animate-blink bg-current align-middle" style={{ height: '0.82em' }} />
    </span>
  );
}
