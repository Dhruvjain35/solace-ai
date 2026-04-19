import { motion } from "framer-motion";
import type { ComfortAction } from "../../types";

type Props = { actions: ComfortAction[] };

/** Editorial clinical style. No emoji. Numbered index chip on the left. */
export function ComfortProtocol({ actions }: Props) {
  return (
    <ol className="flex flex-col gap-3">
      {actions.map((action, i) => (
        <motion.li
          key={`${action.title}-${i}`}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: i * 0.06 }}
          className="bg-surface-lowest rounded-lg shadow-soft p-5 flex gap-4"
        >
          <div className="w-8 h-8 shrink-0 rounded-full bg-primary-fixed text-primary font-bold tracking-editorial flex items-center justify-center text-sm">
            {i + 1}
          </div>
          <div className="flex flex-col gap-1">
            <div className="font-bold tracking-editorial text-base leading-snug">{action.title}</div>
            <div className="text-[15px] text-ink/90 leading-relaxed">{action.instruction}</div>
          </div>
        </motion.li>
      ))}
    </ol>
  );
}
