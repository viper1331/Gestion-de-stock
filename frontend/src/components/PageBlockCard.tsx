import { ReactNode } from "react";
import clsx from "clsx";

type PageBlockCardProps = {
  title?: string;
  actions?: ReactNode;
  header?: ReactNode;
  children: ReactNode;
  variant?: "card" | "plain";
  className?: string;
  bodyClassName?: string;
};

export function PageBlockCard({
  title,
  actions,
  header,
  children,
  variant = "card",
  className,
  bodyClassName
}: PageBlockCardProps) {
  const containerClassName = clsx(
    "min-w-0 overflow-hidden flex flex-col",
    variant === "card" && "rounded-lg border border-slate-800 bg-slate-900",
    className
  );

  const headerContent = header ??
    (title || actions ? (
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div className="min-w-0">
          {title ? <h3 className="truncate text-sm font-semibold text-slate-200">{title}</h3> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    ) : null);

  return (
    <section className={containerClassName}>
      {headerContent}
      <div className={clsx("flex min-h-0 flex-1 flex-col", variant === "card" && "p-4", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}
