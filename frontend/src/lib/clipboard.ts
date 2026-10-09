/**
 * Puts `text` on the clipboard. When the browser refuses (an insecure origin,
 * a lost user gesture) the text is still handed over in a prompt to copy by
 * hand, because the dispatcher pressed the button to paste it somewhere.
 */
export async function copyText(text: string, manualLabel: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    window.prompt(manualLabel, text);
    return false;
  }
}
