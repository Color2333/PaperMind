import type { ReactNode } from "react";
import { Image as ImageIcon, Table2, FileCode2, BarChart3 } from "lucide-react";

export const TYPE_ICONS: Record<string, ReactNode> = {
  figure: <ImageIcon className="h-4 w-4 text-blue-500" />,
  table: <Table2 className="h-4 w-4 text-amber-500" />,
  algorithm: <FileCode2 className="h-4 w-4 text-green-500" />,
  equation: <BarChart3 className="h-4 w-4 text-purple-500" />,
};

export const TYPE_LABELS: Record<string, string> = {
  figure: "图表",
  table: "表格",
  algorithm: "算法",
  equation: "公式",
};
