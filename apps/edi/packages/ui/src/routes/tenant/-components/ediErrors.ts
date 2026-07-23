export interface ParsedEdiError {
  code: string;
  segment: string | null;
  element: string | null;
  globalMessage: string;
  localMessage: string;
  raw: string;
}

export function parseBotsError(errStr: string): ParsedEdiError {
  let code = "UNKNOWN";
  let segment: string | null = null;
  let element: string | null = null;
  let globalMessage = errStr;
  let localMessage = errStr;

  const codeMatch = errStr.match(/^\[([A-Z0-9]+)\]/);
  if (codeMatch) code = codeMatch[1];

  const fieldMatch = errStr.match(/Record "([^"]+)" field "([^"]+)" (.*)/);
  if (fieldMatch) {
    const recordPath = fieldMatch[1];
    element = fieldMatch[2];
    const issue = fieldMatch[3];

    segment = recordPath.split("-").pop() || null;
    if (issue.toLowerCase().includes("mandatory")) {
      globalMessage = `${element} is missing`;
      localMessage = `Missing`;
    } else {
      globalMessage = `${element} ${issue}`;
      localMessage = issue.charAt(0).toUpperCase() + issue.slice(1);
    }
  } else {
    const countMatch = errStr.match(/Count in ([A-Z0-9]+)-([A-Z0-9]+) is \d+; should be equal to number of segments (\d+)/);
    if (countMatch) {
      segment = countMatch[1];
      element = countMatch[2];
      const expected = countMatch[3];
      globalMessage = `${element} must be ${expected}`;
      localMessage = `Must be ${expected}`;
    } else if (codeMatch) {
      const clean = errStr.replace(/^\[[A-Z0-9]+\](:\s*| line \d+ pos \d+:\s*)?/, '');
      globalMessage = clean;
      localMessage = clean;
    }
  }

  return { code, segment, element, globalMessage, localMessage, raw: errStr };
}

export function groupValidationErrors(validationErrors: (string | Record<string, unknown>)[]): {
  parsedErrors: ParsedEdiError[];
  errorMap: Map<string, ParsedEdiError[]>;
} {
  const errorMap = new Map<string, ParsedEdiError[]>();

  const parsedErrors = validationErrors.map(errStr => {
    if (typeof errStr === 'string') {
      return parseBotsError(errStr);
    }
    return errStr; // fallback just in case
  });

  parsedErrors.forEach(err => {
    if (err && err.segment) {
      const list = errorMap.get(err.segment) || [];
      list.push(err);
      errorMap.set(err.segment, list);
    }
  });

  return { parsedErrors, errorMap };
}
