import { createContext, createElement, lazy, useContext, type ComponentProps, type ComponentType } from "react";

/** Each explicit boundary retry gets a fresh lazy import, not a cached rejection. */
export const RouteLoadAttempt = createContext<object>({});

// Match React.lazy's component-first inference, including required route props.
export function retryableLazy<T extends ComponentType<any>>(
  loader: () => Promise<{ default: T }>,
): ComponentType<ComponentProps<T>> {
  type Props = ComponentProps<T>;
  const attempts = new WeakMap<object, ComponentType<Props>>();
  return function RetryableScreen(props: Props) {
    const attempt = useContext(RouteLoadAttempt);
    let Screen = attempts.get(attempt);
    if (!Screen) {
      Screen = lazy(loader) as ComponentType<Props>;
      attempts.set(attempt, Screen);
    }
    return createElement(Screen, props);
  };
}
