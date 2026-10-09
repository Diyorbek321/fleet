import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy } from 'lucide-react';

import { Button, type ButtonProps } from '@/components/ui/button';
import { toast } from '@/hooks/use-toast';
import { copyText } from '@/lib/clipboard';
import { cn } from '@/lib/utils';

interface CopyButtonProps {
  /** What lands on the clipboard. */
  text: string;
  /** Tooltip and screen-reader label. */
  label: string;
  /** Shown beside the icon; left out, the button is icon-only. */
  children?: React.ReactNode;
  size?: ButtonProps['size'];
  variant?: ButtonProps['variant'];
  className?: string;
}

/** A copy button that ticks for a moment once the text is on the clipboard. */
export function CopyButton({ text, label, children, size, variant = 'ghost', className }: CopyButtonProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const Icon = copied ? Check : Copy;
  const iconOnly = !children;
  return (
    <Button
      type="button"
      size={size ?? (iconOnly ? 'icon' : 'sm')}
      variant={variant}
      className={cn(iconOnly && size === undefined && 'h-7 w-7', className)}
      title={label}
      aria-label={label}
      onClick={async (e) => {
        // Rows that hold this button usually navigate on click.
        e.stopPropagation();
        if (await copyText(text, t('common.copyManually'))) {
          setCopied(true);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setCopied(false), 1500);
          toast({ title: t('common.copied') });
        }
      }}
    >
      <Icon className={cn('h-3.5 w-3.5', !iconOnly && 'mr-2 h-4 w-4', copied && 'text-status-moving')} />
      {children}
    </Button>
  );
}
