import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FileUp, HardDrive } from 'lucide-react';
import { normalizeRunnerPathInput } from '@/lib/webMode';

interface FileSelectorProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onContentLoaded?: (content: string) => void;
  placeholder?: string;
  optional?: boolean;
  onSelectLocal: () => Promise<string | null>;
  onReadLocalContent?: (path: string) => Promise<string>;
  disableLocalPicker?: boolean;
  pathInputMode?: boolean;
  pathInputPlaceholder?: string;
}

export default function FileSelector({
  label,
  value,
  onChange,
  onContentLoaded,
  placeholder = 'Select a file...',
  optional = false,
  onSelectLocal,
  onReadLocalContent,
  disableLocalPicker = false,
  pathInputMode = false,
  pathInputPlaceholder,
}: FileSelectorProps) {
  const [isSelecting, setIsSelecting] = useState(false);
  const selectInFlightRef = useRef(false);

  const handleSelectLocal = useCallback(async () => {
    if (selectInFlightRef.current) return;
    selectInFlightRef.current = true;
    setIsSelecting(true);
    try {
      const path = await onSelectLocal();
      if (path) {
        onChange(path);
        if (onContentLoaded && onReadLocalContent) {
          const content = await onReadLocalContent(path);
          if (content) {
            onContentLoaded(content);
          }
        }
      }
    } finally {
      selectInFlightRef.current = false;
      setIsSelecting(false);
    }
  }, [onSelectLocal, onChange, onContentLoaded, onReadLocalContent]);

  const displayValue = value
    ? pathInputMode
      ? value
      : value.split('/').pop() || value
    : '';

  const inputValue = pathInputMode ? value : displayValue;
  const inputPlaceholder = pathInputPlaceholder ?? placeholder;

  useEffect(() => {
    if (!pathInputMode || !value || !onReadLocalContent || !onContentLoaded) return;
    if (value.startsWith('web://')) return;

    const trimmedPath = normalizeRunnerPathInput(value);
    if (!trimmedPath) return;

    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const content = await onReadLocalContent(trimmedPath);
          if (!cancelled && content) {
            onContentLoaded(content);
          }
        } catch {
          // Path may be incomplete or unavailable until the runner can read it.
        }
      })();
    }, 400);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [pathInputMode, value, onReadLocalContent, onContentLoaded]);

  return (
    <div className="space-y-1">
      <Label className="text-xs font-medium text-muted-foreground">
        {label}
        {optional && <span className="ml-1 text-muted-foreground/60">(optional)</span>}
      </Label>

      <div className="flex gap-2">
        <div className="relative flex-1">
          <Input
            value={inputValue}
            onChange={(e) => onChange(e.target.value)}
            onBlur={() => {
              if (!pathInputMode) return;
              const trimmed = normalizeRunnerPathInput(value);
              if (trimmed !== value) {
                onChange(trimmed);
              }
            }}
            placeholder={inputPlaceholder}
            className="h-8 pr-8"
          />
          {value ? (
            <HardDrive className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          ) : null}
        </div>

        {!disableLocalPicker ? (
          <Button
            variant="outline"
            size="icon"
            onClick={() => void handleSelectLocal()}
            disabled={isSelecting}
            className="h-8 w-8 shrink-0"
            title="Select from local filesystem"
          >
            <FileUp className="h-4 w-4" />
          </Button>
        ) : null}
      </div>

      {pathInputMode ? (
        <p className="text-[11px] text-muted-foreground">
          Type a path accessible to the local runner on this machine.
        </p>
      ) : null}
    </div>
  );
}
