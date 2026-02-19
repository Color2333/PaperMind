/**
 * ImageUploader - 图片上传组件（拖拽 + 粘贴 + 点击选文件）
 * @author Bamzc
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { ImagePlus, X, Upload } from "lucide-react";

interface ImageUploaderProps {
  value: string | null;
  onChange: (base64: string | null) => void;
  className?: string;
  hint?: string;
}

const MAX_SIZE = 10 * 1024 * 1024;
const ACCEPTED = ["image/png", "image/jpeg", "image/webp", "image/gif"];

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(",")[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function ImageUploader({ value, onChange, className = "", hint }: ImageUploaderProps) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (value) {
      setPreviewUrl(`data:image/png;base64,${value}`);
    } else {
      setPreviewUrl(null);
    }
  }, [value]);

  const processFile = useCallback(async (file: File) => {
    setError(null);
    if (!ACCEPTED.includes(file.type)) {
      setError("仅支持 PNG / JPG / WebP / GIF 格式");
      return;
    }
    if (file.size > MAX_SIZE) {
      setError("图片大小不能超过 10MB");
      return;
    }
    try {
      const b64 = await fileToBase64(file);
      onChange(b64);
    } catch {
      setError("读取图片失败");
    }
  }, [onChange]);

  // 粘贴事件
  useEffect(() => {
    const handler = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) processFile(file);
          return;
        }
      }
    };
    document.addEventListener("paste", handler);
    return () => document.removeEventListener("paste", handler);
  }, [processFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }, [processFile]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    if (inputRef.current) inputRef.current.value = "";
  }, [processFile]);

  if (value && previewUrl) {
    return (
      <div className={`relative inline-block ${className}`}>
        <div className="group relative overflow-hidden rounded-xl border border-border bg-page">
          <img src={previewUrl} alt="上传的图片" className="max-h-48 max-w-full rounded-xl object-contain" />
          <button
            onClick={() => onChange(null)}
            className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-black/50 text-white opacity-0 transition-opacity hover:bg-black/70 group-hover:opacity-100"
            title="移除图片"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      <div
        ref={dropRef}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-5 transition-all ${
          dragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/40 hover:bg-page/50"
        }`}
      >
        <div className={`rounded-lg p-2 ${dragOver ? "bg-primary/10" : "bg-page"}`}>
          {dragOver ? <Upload className="h-5 w-5 text-primary" /> : <ImagePlus className="h-5 w-5 text-ink-tertiary" />}
        </div>
        <div className="text-center">
          <p className="text-xs font-medium text-ink-secondary">
            {dragOver ? "松手上传" : "拖拽图片到此处，或点击选择"}
          </p>
          <p className="mt-0.5 text-[10px] text-ink-tertiary">
            {hint || "支持 Ctrl+V 粘贴截图 · PNG/JPG/WebP · 最大 10MB"}
          </p>
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={handleFileSelect}
      />
      {error && <p className="mt-1.5 text-xs text-error">{error}</p>}
    </div>
  );
}
