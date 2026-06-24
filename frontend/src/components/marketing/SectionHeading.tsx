import { ReactNode } from "react";
import { Eyebrow } from "./Eyebrow";
import { Reveal } from "./Reveal";

type Props = {
  eyebrow: string;
  title: ReactNode;
  sub?: ReactNode;
  align?: "center" | "left";
  inverse?: boolean;
};

/** Eyebrow + serif section title + optional sub-line. */
export function SectionHeading({ eyebrow, title, sub, align = "center", inverse }: Props) {
  const alignCls = align === "center" ? "text-center items-center" : "text-left items-start";
  return (
    <Reveal className={`flex flex-col gap-4 ${alignCls}`}>
      <Eyebrow tone={inverse ? "inverse" : "teal"}>{eyebrow}</Eyebrow>
      <h2
        className={`font-display text-3xl sm:text-4xl lg:text-[44px] leading-[1.08] tracking-editorial ${
          inverse ? "text-white" : "text-ink"
        }`}
      >
        {title}
      </h2>
      {sub && (
        <p className={`max-w-2xl text-base sm:text-lg ${inverse ? "text-primary-fixed/85" : "text-text-muted"}`}>
          {sub}
        </p>
      )}
    </Reveal>
  );
}
