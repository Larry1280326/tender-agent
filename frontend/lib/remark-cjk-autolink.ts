// GFM autolink 只以 ASCII 標點／空白作為 URL 終止符，全形標點（（）、：等）會被吞進
// URL。此 plugin 喺 remark-gfm 之後執行，把黏喺 URL 尾部嘅全形註解（例如
// （公告日期：2026年9月1日））由連結度剝離，還原做連結外面嘅純文字。

type Node = {
  type: string;
  url?: string;
  value?: string;
  children?: Node[];
};

// URL 入面理論上唔會出現「原始」全形標點（有都會被 percent-encode），所以只要喺 URL
// 度搵到第一個全形標點／括號，就代表 URL 已經完、後面係中文註解。
const CJK_TERMINATORS = "（）。，、：；！？…．【】《》「」『』〈〉［］";

function splitCjkAnnotation(url: string): { url: string; annotation: string } {
  for (let i = 0; i < url.length; i++) {
    if (CJK_TERMINATORS.includes(url[i])) {
      return { url: url.slice(0, i), annotation: url.slice(i) };
    }
  }
  return { url, annotation: "" };
}

export default function remarkCjkAutolink() {
  const fix = (node: Node, parent: Node | null, index: number) => {
    if (node.type === "link" && node.url) {
      const { url, annotation } = splitCjkAnnotation(node.url);
      if (annotation) {
        node.url = url;
        const text = node.children?.find((c) => c.type === "text");
        if (text) text.value = url;
        parent?.children?.splice(index + 1, 0, { type: "text", value: annotation });
      }
    }
    node.children?.forEach((child, i) => fix(child, node, i));
  };
  return (tree: Node) => fix(tree, null, -1);
}
