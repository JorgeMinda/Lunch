import { motion } from 'framer-motion'
import {
  ArrowRight,
  ScanLine,
  ShieldCheck,
  UtensilsCrossed,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface RoleCard {
  title: string
  description: string
  icon: LucideIcon
  accent: string
}

const roles: RoleCard[] = [
  {
    title: 'Padres y alumnos',
    description:
      'Menú semanal, saldo disponible, historial de consumos y QR del estudiante.',
    icon: Users,
    accent: 'bg-brand-100 text-brand-700',
  },
  {
    title: 'Administración',
    description:
      'Gestión de estudiantes, menús y liberación de saldos tras validar pagos.',
    icon: ShieldCheck,
    accent: 'bg-amber-100 text-amber-700',
  },
  {
    title: 'Cocina / Caja',
    description:
      'Escaneo QR ultrarrápido y descuento de uno o varios almuerzos al instante.',
    icon: ScanLine,
    accent: 'bg-sky-100 text-sky-700',
  },
]

function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <span className="flex size-10 items-center justify-center rounded-xl bg-brand-700 text-white">
            <UtensilsCrossed className="size-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-lg font-semibold leading-tight text-slate-900">
              Lunch
            </p>
            <p className="text-xs text-slate-500">Comedor escolar</p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-14">
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className="max-w-2xl"
        >
          <span className="inline-flex items-center rounded-full bg-brand-100 px-3 py-1 text-xs font-medium text-brand-800">
            Proyecto base · Arquitectura hexagonal
          </span>
          <h1 className="mt-5 text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
            Sistema de gestión para comedores escolares
          </h1>
          <p className="mt-4 text-base leading-relaxed text-slate-600">
            Base modular lista para conectar Supabase: dominio, casos de uso,
            infraestructura y presentación separados por rol.
          </p>
        </motion.section>

        <section className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {roles.map((role, index) => {
            const Icon = role.icon

            return (
              <motion.article
                key={role.title}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.35,
                  delay: 0.08 * (index + 1),
                  ease: 'easeOut',
                }}
                className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
              >
                <span
                  className={`flex size-11 items-center justify-center rounded-xl ${role.accent}`}
                >
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <h2 className="mt-4 text-base font-semibold text-slate-900">
                  {role.title}
                </h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">
                  {role.description}
                </p>
                <span className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-brand-700">
                  Próximamente
                  <ArrowRight className="size-4" aria-hidden="true" />
                </span>
              </motion.article>
            )
          })}
        </section>
      </main>
    </div>
  )
}

export default App
