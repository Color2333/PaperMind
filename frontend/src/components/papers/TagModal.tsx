import { Button, Input, Modal } from "@/components/ui";
import type { Tag as TagType } from "@/types";

/* ========== 标签管理弹窗 ========== */
function TagModal({
  open,
  onClose,
  editingTag,
  tagName,
  tagColor,
  onNameChange,
  onColorChange,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  editingTag: TagType | null;
  tagName: string;
  tagColor: string;
  onNameChange: (name: string) => void;
  onColorChange: (color: string) => void;
  onSave: () => void;
}) {
  const presetColors = [
    "#3b82f6",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#84cc16",
  ];

  return (
    <Modal open={open} onClose={onClose} title={editingTag ? "编辑标签" : "新建标签"}>
      <div className="space-y-4">
        <Input
          label="标签名称"
          placeholder="输入标签名称"
          value={tagName}
          onChange={(e) => onNameChange(e.target.value)}
        />
        <div className="space-y-2">
          <label className="text-ink block text-sm font-medium">标签颜色</label>
          <div className="flex flex-wrap gap-2">
            {presetColors.map((color) => (
              <button
                key={color}
                onClick={() => onColorChange(color)}
                className={`h-8 w-8 rounded-full transition-transform ${
                  tagColor === color ? "ring-2 ring-offset-2" : "hover:scale-110"
                }`}
                style={{
                  backgroundColor: color,
                  boxShadow: tagColor === color ? `0 0 0 2px ${color}` : "none",
                }}
              />
            ))}
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={tagColor}
                onChange={(e) => onColorChange(e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border-0"
              />
              <span className="text-ink-tertiary text-[11px]">{tagColor}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 pt-2">
          <span className="text-ink-tertiary text-sm">预览：</span>
          <span
            className="inline-flex items-center rounded-md px-3 py-1 text-sm font-medium"
            style={{
              backgroundColor: `${tagColor}20`,
              color: tagColor,
            }}
          >
            {tagName || "标签名称"}
          </span>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onSave}>{editingTag ? "保存" : "创建"}</Button>
        </div>
      </div>
    </Modal>
  );
}

export default TagModal;
