import { Mail, ShieldCheck } from 'lucide-react';
import { useAuth } from 'react-oidc-context';

export function IdentityDetailsCard() {
  const auth = useAuth();
  const email = auth.user?.profile.email;
  const name = auth.user?.profile.name;

  if (!email || !name) {
    return (
      <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 h-[160px] animate-pulse">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="h-14 w-14 rounded-xl bg-slate-100"></div>
            <div className="flex flex-col gap-2">
              <div className="h-5 w-32 bg-slate-100 rounded"></div>
              <div className="h-4 w-40 bg-slate-100 rounded"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-indigo-500/30 hover:-translate-y-0.5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-indigo-50 border border-indigo-100 shadow-sm overflow-hidden text-indigo-600 font-black text-2xl uppercase">
            {name.charAt(0)}
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">{name}</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <Mail className="h-4 w-4 text-slate-400" /> {email}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-bold border border-emerald-100 shadow-sm">
          <ShieldCheck className="w-3.5 h-3.5" /> Verified
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-4">
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-0.5">
            Role
          </p>
          <p className="text-sm font-bold text-slate-800">Administrator</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-0.5">
            Auth
          </p>
          <p className="text-sm font-bold text-slate-800">Zitadel SSO</p>
        </div>
      </div>
    </div>
  );
}
