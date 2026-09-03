"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkCjkAutolink from "@/lib/remark-cjk-autolink";

export default memo(function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkCjkAutolink]}
      components={{
        a: ({ node, ...props }) => (
          <a {...props} target="_blank" rel="noopener noreferrer" />
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
});
