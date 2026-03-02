/// <reference types="vite/client" />

// SVG 组件类型定义（vite-plugin-svgr）
declare module "*.svg?react" {
  import { FC, SVGProps } from "react";
  const component: FC<SVGProps<SVGSVGElement>>;
  export default component;
}

declare module "*.svg" {
  const src: string;
  export default src;
}
