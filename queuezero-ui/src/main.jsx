import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Admin from './Admin.jsx'
import Login from './Login.jsx'
import Landing from './Landing.jsx'

const path = window.location.pathname

const Page =
  path.startsWith('/admin') ? Admin   :
  path.startsWith('/login') ? Login   :
  path.startsWith('/app')   ? App     :
                              Landing

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Page />
  </StrictMode>,
)
