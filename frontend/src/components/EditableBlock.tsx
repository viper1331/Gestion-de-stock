import { ReactNode } from "react";

type EditableBlockProps = {
  id: string;
  className?: string;
  children: ReactNode;
};

export function EditableBlock({ id, className, children }: EditableBlockProps) {
  const combinedClassName = className ? `min-w-0 max-w-full ${className}` : "min-w-0 max-w-full";
  return (
    <div data-editable-block={id} className={combinedClassName}>
      {children}
    </div>
  );
}
