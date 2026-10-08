import type { ReactNode, SVGProps } from "react";

export type IconName =
  | "activity"
  | "arrow"
  | "board"
  | "bot"
  | "branch"
  | "chat"
  | "check"
  | "chevron"
  | "clock"
  | "cpu"
  | "dashboard"
  | "database"
  | "file"
  | "flask"
  | "folder"
  | "info"
  | "layers"
  | "lock"
  | "merge"
  | "menu"
  | "microphone"
  | "paperclip"
  | "pause"
  | "play"
  | "refresh"
  | "search"
  | "send"
  | "split"
  | "sliders"
  | "sparkles"
  | "stop"
  | "tasks"
  | "users"
  | "x";

const paths: Record<IconName, ReactNode> = {
  activity: <path d="M3 12h4l2.5-7 5 14 2.5-7h4" />,
  arrow: <path d="m9 18 6-6-6-6" />,
  board: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16M15 4v16M3 10h6M15 13h6" />
    </>
  ),
  bot: (
    <>
      <rect x="4" y="7" width="16" height="13" rx="3" />
      <path d="M12 3v4M8.5 12h.01M15.5 12h.01M8 16h8" />
    </>
  ),
  branch: (
    <>
      <circle cx="6" cy="5" r="2" />
      <circle cx="18" cy="7" r="2" />
      <circle cx="6" cy="19" r="2" />
      <path d="M6 7v10M8 7h4a6 6 0 0 1 6 6v-4" />
    </>
  ),
  chat: (
    <>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h-1A2.5 2.5 0 0 1 4 13.5v-8Z" />
      <path d="M8 8h8M8 11.5h5" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
      <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7" />
    </>
  ),
  file: (
    <>
      <path d="M7 3h7l5 5v13H7V3Z" />
      <path d="M14 3v5h5M10 13h5M10 17h5" />
    </>
  ),
  flask: (
    <>
      <path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3" />
      <path d="M7.5 15h9" />
    </>
  ),
  folder: (
    <path d="M3 6.5A2.5 2.5 0 0 1 5.5 4H10l2 2h6.5A2.5 2.5 0 0 1 21 8.5v9A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5v-11Z" />
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  merge: <path d="M7 3v5a4 4 0 0 0 4 4h6m0 0-3-3m3 3-3 3M7 21v-5a4 4 0 0 1 4-4" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  microphone: (
    <>
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7" />
    </>
  ),
  paperclip: <path d="m9 12.5 6.2-6.2a3 3 0 1 1 4.2 4.2l-8.1 8.1a5 5 0 0 1-7.1-7.1l8.2-8.2M7.1 14.4l8.1-8.1" />,
  pause: <path d="M9 5v14M15 5v14" />,
  play: <path d="m8 5 10 7-10 7V5Z" />,
  refresh: <path d="M20 7v5h-5M4 17v-5h5M18.2 9A7 7 0 0 0 6.1 6.4L4 8M5.8 15A7 7 0 0 0 17.9 17.6L20 16" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m16 16 5 5" />
    </>
  ),
  send: <path d="M4 12 20 4l-4 16-4-7-8-1Z" />,
  split: <path d="M7 3v5a4 4 0 0 0 4 4h6m0 0-3-3m3 3-3 3M11 12a4 4 0 0 0-4 4v5" />,
  sliders: (
    <>
      <path d="M4 6h5M13 6h7M4 12h9M17 12h3M4 18h3M11 18h9" />
      <circle cx="11" cy="6" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="9" cy="18" r="2" />
    </>
  ),
  sparkles: (
    <>
      <path d="m12 3 1.1 3.1L16 7.5l-2.9 1.4L12 12l-1.1-3.1L8 7.5l2.9-1.4L12 3Z" />
      <path d="m18.5 13 .7 1.8L21 15.5l-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8ZM5.5 13l.7 1.8 1.8.7-1.8.7L5.5 18l-.7-1.8-1.8-.7 1.8-.7.7-1.8Z" />
    </>
  ),
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  tasks: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="m8 9 1.5 1.5L12 8M14 9h3M8 15h9" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <circle cx="16.5" cy="9" r="2.5" />
      <path d="M15.5 14.4a4.6 4.6 0 0 1 5 4.6" />
    </>
  ),
  x: <path d="m6 6 12 12M18 6 6 18" />,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="20"
      viewBox="0 0 24 24"
      width="20"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
