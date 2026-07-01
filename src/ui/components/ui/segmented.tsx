import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  "aria-label"?: string;
}

/**
 * Compact segmented pill (like a trading-chart "1M/3M/6M" control). The
 * active segment is highlighted with the app's primary accent; the group
 * sits inside a muted rounded track. Buttons expose aria-pressed for a11y.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  "aria-label": ariaLabel,
}: SegmentedProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center rounded-lg bg-muted p-[3px] text-muted-foreground",
        className
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "inline-flex h-7 items-center justify-center rounded-md px-3 text-xs font-medium transition-all outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px]",
              active
                ? "bg-primary text-primary-foreground shadow-sm"
                : "hover:text-foreground"
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
