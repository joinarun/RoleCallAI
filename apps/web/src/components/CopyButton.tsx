import { useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return <button className="icon-button" type="button" onClick={() => void copy()} aria-label={`${label} link`}>{copied ? <Check size={17} /> : <Copy size={17} />}<span>{copied ? "Copied" : label}</span></button>;
}
