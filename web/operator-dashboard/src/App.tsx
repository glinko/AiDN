import ClassicDashboard from '@/app/classic-dashboard'

/**
 * Composition entry point for the operator dashboard.
 *
 * Keep route boundaries and providers outside this module; the Classic
 * implementation can migrate screen-by-screen without growing this root.
 */
export default function App() {
  return <ClassicDashboard />
}
