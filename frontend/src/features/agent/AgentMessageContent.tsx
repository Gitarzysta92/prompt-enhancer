import {
  isValidElement,
  type AnchorHTMLAttributes,
  type ReactNode,
} from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AgentCopyButton } from "./AgentCopyButton";
import "./AgentMessageContent.css";

type Props = {
  content: string;
  linkPolicy?: "safe_external" | "inert";
  onOpenWorkspaceFile?: (path: string) => void;
  variant?: "assistant" | "user" | "reasoning" | "artifact";
};

const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);
const WORKSPACE_LINK_PREFIX = "workspace:";

function workspaceLinkPath(url: string): string | null {
  if (!url.startsWith(WORKSPACE_LINK_PREFIX)) return null;
  let path: string;
  try {
    path = decodeURIComponent(url.slice(WORKSPACE_LINK_PREFIX.length));
  } catch {
    return null;
  }
  if (
    !path
    || path.length > 1024
    || path.startsWith("/")
    || path.startsWith("\\")
    || /^[A-Za-z]:/u.test(path)
    || /[\x00-\x1f\x7f?#]/u.test(path)
  ) return null;
  const segments = path.split(/[\\/]/u);
  return segments.some((segment) => segment === "" || segment === "." || segment === "..")
    ? null
    : path.replaceAll("\\", "/");
}

function safeMarkdownUrl(url: string, key: string): string {
  if (key === "src") return "";
  if (workspaceLinkPath(url) !== null) return url;
  if (url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    return ALLOWED_PROTOCOLS.has(parsed.protocol) ? url : "";
  } catch {
    return "";
  }
}

function isExternalWebLink(href: string): boolean {
  try {
    const protocol = new URL(href).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textContent(node.props.children);
  return "";
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const child = Array.isArray(children) ? children[0] : children;
  const className = isValidElement<{ className?: string }>(child) ? child.props.className ?? "" : "";
  const language = /(?:^|\s)language-([\w.+-]+)/u.exec(className)?.[1] ?? "code";
  const code = textContent(child).replace(/\n$/u, "");

  return (
    <div className="agent-markdown__code">
      <div className="agent-markdown__code-head">
        <span>{language}</span>
        <AgentCopyButton label={`Copy ${language} code`} value={code} />
      </div>
      <pre>{children}</pre>
    </div>
  );
}

function SafeLink({ children, href, linkPolicy, onOpenWorkspaceFile, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & {
  linkPolicy: NonNullable<Props["linkPolicy"]>;
  onOpenWorkspaceFile?: Props["onOpenWorkspaceFile"];
}) {
  if (linkPolicy === "inert") {
    return (
      <span className="agent-markdown__inert-link" title="Links stay inert in verified artifact previews">
        {children}
      </span>
    );
  }
  if (!href) return <span className="agent-markdown__blocked-link">{children}</span>;
  const workspacePath = workspaceLinkPath(href);
  if (workspacePath !== null) {
    return onOpenWorkspaceFile ? (
      <button
        className="agent-markdown__workspace-link"
        onClick={() => onOpenWorkspaceFile(workspacePath)}
        title={`Open ${workspacePath} in Files & review`}
        type="button"
      >
        {children}
      </button>
    ) : (
      <span className="agent-markdown__inert-link" title="Resume this chat to open workspace files">
        {children}
      </span>
    );
  }
  const external = isExternalWebLink(href);
  return (
    <a
      {...props}
      href={href}
      rel={external ? "noreferrer noopener" : undefined}
      target={external ? "_blank" : undefined}
    >
      {children}
    </a>
  );
}

export function AgentMessageContent({ content, linkPolicy = "safe_external", onOpenWorkspaceFile, variant = "assistant" }: Props) {
  return (
    <div className="agent-markdown" data-variant={variant}>
      <Markdown
        components={{
          a(props) {
            return <SafeLink {...props} linkPolicy={linkPolicy} onOpenWorkspaceFile={onOpenWorkspaceFile} />;
          },
          img({ alt }) {
            return (
              <span className="agent-markdown__blocked-image" role="note">
                {alt ? `Remote image omitted: ${alt}` : "Remote image omitted"}
              </span>
            );
          },
          pre({ children }) {
            return <CodeBlock>{children}</CodeBlock>;
          },
          table({ children, ...props }) {
            return <div className="agent-markdown__table"><table {...props}>{children}</table></div>;
          },
        }}
        remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
        skipHtml
        urlTransform={safeMarkdownUrl}
      >
        {content}
      </Markdown>
    </div>
  );
}
