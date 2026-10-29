import { useEffect } from 'react';

export interface ProductThemeRootTarget {
  readonly dataset: {
    productTheme?: string;
  };
}

/**
 * Applies a caller-supplied product theme token onto a root element's dataset
 * and returns a deterministic cleanup function that restores the prior state.
 */
export function applyProductTheme(
  root: ProductThemeRootTarget,
  themeToken?: string | null,
): () => void {
  const previousTheme = root.dataset.productTheme;

  if (!themeToken) {
    delete root.dataset.productTheme;
  } else {
    root.dataset.productTheme = themeToken;
  }

  return () => {
    if (previousTheme === undefined) {
      delete root.dataset.productTheme;
    } else {
      root.dataset.productTheme = previousTheme;
    }
  };
}

/**
 * Generic IoC hook that scopes semantic CSS custom properties on document.documentElement
 * using any caller-supplied product theme token (null/undefined restores platform default).
 */
export function useProductTheme(themeToken?: string | null): void {
  useEffect(() => {
    if (typeof document === 'undefined') {
      return undefined;
    }
    return applyProductTheme(document.documentElement, themeToken);
  }, [themeToken]);
}
