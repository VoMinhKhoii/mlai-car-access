import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'

// `?ui=v2` opts into the map-first redesign; the team's current UI stays the default.
const AppV2 = lazy(() => import('./v2/AppV2.tsx'))
const v2 = new URLSearchParams(window.location.search).get('ui') === 'v2'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {v2 ? <Suspense fallback={null}><AppV2 /></Suspense> : <App />}
  </StrictMode>,
)
