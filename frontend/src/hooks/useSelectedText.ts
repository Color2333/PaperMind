import { useState, useCallback, useEffect } from 'react';

export function useSelectedText() {
  const [selectedText, setSelectedText] = useState('');

  useEffect(() => {
    const handler = () => {
      const sel = window.getSelection()?.toString().trim();
      if (sel && sel.length > 2) {
        setSelectedText(sel);
      }
    };
    document.addEventListener('mouseup', handler);
    return () => document.removeEventListener('mouseup', handler);
  }, []);

  return selectedText;
}
