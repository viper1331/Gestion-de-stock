import { ReactNode } from "react";

type SafeBlockProps = {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
};

export function SafeBlock({ children, className, innerClassName }: SafeBlockProps) {
  const outerClassName = [
    "safe-block",
    "min-w-0 max-w-full h-full overflow-hidden",
    className
  ]
    .filter(Boolean)
    .join(" ");
  const contentClassName = [
    "block-content",
    "min-w-0 max-w-full h-full overflow-hidden",
    innerClassName
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={outerClassName} data-safe-block>
      <div className={contentClassName}>{children}</div>
    </div>
  );
}
