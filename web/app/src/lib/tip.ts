/* Singleton tooltip, same behaviour as the prototype's #tip. */
let node: HTMLDivElement | null = null;
function el(): HTMLDivElement {
  if (!node) {
    node = document.createElement("div");
    node.className = "tip";
    node.hidden = true;
    node.setAttribute("role", "tooltip");
    document.body.appendChild(node);
  }
  return node;
}
export function showTip(text: string, x: number, y: number) {
  const n = el();
  n.textContent = text;
  n.style.left = x + "px";
  n.style.top = y + "px";
  n.hidden = false;
}
export function hideTip() {
  if (node) node.hidden = true;
}
type P = { clientX: number; clientY: number };
/** Spread onto an SVG/HTML element to get a hover tooltip. */
export function tip(text: string | (() => string)) {
  const get = () => (typeof text === "function" ? text() : text);
  return {
    onPointerEnter: (e: P) => showTip(get(), e.clientX, e.clientY),
    onPointerMove: (e: P) => showTip(get(), e.clientX, e.clientY),
    onPointerLeave: hideTip,
  };
}
