import { BrowserRouter, Route, Routes } from 'react-router-dom'
import CampaignDetail from './pages/CampaignDetail'
import Dashboard from './pages/Dashboard'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/campaigns/:id" element={<CampaignDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
