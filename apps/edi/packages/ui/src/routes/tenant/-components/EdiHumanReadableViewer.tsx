import { AlertTriangle } from 'lucide-react';
import { useEdiDictionary } from './useEdiDictionary';
import { groupValidationErrors } from './ediErrors';

interface ViewerProps {
  data: any; // The JSON AST
  validationErrors: string[];
}

export function EdiHumanReadableViewer({ data, validationErrors }: ViewerProps) {
  const { dictionary, loading } = useEdiDictionary(data);

  if (loading) {
    return <div className="p-4 text-slate-500 animate-pulse">Loading dictionary...</div>;
  }

  if (!dictionary) {
    return <div className="p-4 text-red-500">Failed to load EDI descriptions.</div>;
  }

  const { parsedErrors, errorMap } = groupValidationErrors(validationErrors);

  // Recursive function to render a node
  const renderNode = (key: string, value: any, depth = 0) => {
    if (Array.isArray(value)) {
      return value.map((item, index) => (
        <div key={`${key}-${index}`} className="ml-4 border-l-2 border-slate-100 pl-4 py-2 mt-2">
          {renderNode(key, item, depth + 1)}
        </div>
      ));
    }

    if (typeof value === 'object' && value !== null) {
      return Object.entries(value).map(([childKey, childValue]) => {


        const segDef = dictionary.segments[childKey];
        const segErrors = errorMap.get(childKey) || [];
        const hasSegError = segErrors.length > 0;

        // If it's a known segment, render it nicely
        if (segDef && typeof childValue === 'object' && childValue !== null) {
          const headerBgClass = hasSegError ? 'bg-red-50' : 'bg-emerald-50';
          const headerTextClass = hasSegError ? 'text-red-900' : 'text-emerald-900';
          const badgeClass = hasSegError ? 'bg-red-600' : 'bg-emerald-600';

          const elemErrors = segErrors.filter(e => e.element);
          const segmentOnlyErrors = segErrors.filter(e => !e.element);
          const hasHeaderErrors = segmentOnlyErrors.length > 0;

          // If an error is for a missing element, inject it so it gets rendered
          const elementsToRender: Record<string, any> = { ...childValue };
          elemErrors.forEach(err => {
            if (err.element && !(err.element in elementsToRender)) {
              elementsToRender[err.element] = "";
            }
          });

          return (
            <div key={childKey} className={`mb-3 bg-white rounded-lg border ${hasSegError ? 'border-red-300' : ''} shadow-sm overflow-hidden`}>
              <div className={`${headerBgClass} px-4 py-2 border-b flex items-center justify-between`}>
                <div className={`font-semibold ${headerTextClass} flex items-center gap-2`}>
                  <span className={`${badgeClass} text-white text-xs px-2 py-1 rounded font-mono`}>{childKey}</span>
                  <span>{segDef.info}</span>
                </div>
              </div>

              {hasHeaderErrors && (
                <div className="bg-red-50 border-b border-red-200 px-4 py-2">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
                    <ul className="text-sm font-medium text-red-700">
                      {segmentOnlyErrors.map((err, idx) => (
                        <li key={idx}>{err.localMessage}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              <div className="p-4 bg-slate-50 grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.entries(elementsToRender).map(([elemKey, elemValue]) => {
                  const match = elemKey.match(/^[A-Z0-9]+(\d{2})$/);
                  let elemDesc = 'Unknown Element';
                  if (match) {
                    const idx = parseInt(match[1], 10) - 1; // 01 is index 0
                    const fRef = segDef.elements[idx];
                    if (fRef) {
                      elemDesc = dictionary.elements[fRef] || elemDesc;
                    }
                  }

                  const myErrors = elemErrors.filter(e => e.element === elemKey);
                  const isElemError = myErrors.length > 0;
                  const elemTextClass = isElemError ? 'text-red-600' : 'text-emerald-600';
                  const elemBgClass = isElemError ? 'bg-red-50 border-red-200 shadow-sm' : 'bg-white';
                  const textColorClass = isElemError && elemValue === ''
                                         ? 'text-red-400 italic'
                                         : (isElemError ? 'text-red-900 font-bold' : 'text-slate-900');

                  return (
                    <div key={elemKey} className={`flex flex-col p-3 rounded border ${elemBgClass}`}>
                      <span className="text-xs font-semibold text-slate-500 uppercase flex items-center gap-2">
                        <span className={elemTextClass}>{elemKey}</span>
                        <span className="truncate">{elemDesc}</span>
                      </span>
                      {elemValue !== '' && (
                        <span className={`text-sm font-medium mt-1 break-all ${textColorClass}`}>
                          {typeof elemValue === 'string' ? elemValue : JSON.stringify(elemValue)}
                        </span>
                      )}
                      {isElemError && (
                        <div className={`flex flex-col gap-1 ${elemValue !== '' ? 'mt-2 pt-2 border-t border-red-200' : 'mt-1'}`}>
                          {myErrors.map((err, idx) => (
                            <div key={idx} className="flex items-center gap-1.5 text-red-700 text-xs font-semibold">
                              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                              <span>{err.localMessage}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        }

        // Otherwise, it's a loop wrapper or standard container
        return (
          <div key={childKey} className="mt-2">
            {depth > 0 && <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Loop {childKey}</div>}
            {renderNode(childKey, childValue, depth + 1)}
          </div>
        );
      });
    }

    return (
      <span className="text-sm font-medium text-slate-800 break-all">
        {String(value)}
      </span>
    );
  };

  // The root structure usually has the transactions object
  // bots AST typically: data -> {"type": "message", "record": { "ST": ... }} or similar
  const astRoot = data?.record || data;

  return (
    <div className="p-4 overflow-y-auto h-full bg-slate-100/50">
      {parsedErrors.length > 0 && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-4 shadow-sm shrink-0">
          <h3 className="text-red-900 font-bold uppercase tracking-wider text-sm flex items-center gap-2 mb-2">
            <AlertTriangle className="w-5 h-5 text-red-600" />
            Validation Errors Summary
          </h3>
          <ul className="list-disc list-inside text-red-700 text-sm space-y-1 font-medium">
            {parsedErrors.map((err, i) => (
              <li key={i}>{err.globalMessage || err.raw}</li>
            ))}
          </ul>
        </div>
      )}
      {renderNode("root", astRoot)}
    </div>
  );
}
