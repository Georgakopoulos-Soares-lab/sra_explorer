import { BrowserRouter, Route, Routes } from 'react-router'
import AppLayout from './components/AppLayout'
import ApiDocsPage from './pages/ApiDocsPage'
import FilesPage from './pages/FilesPage'
import HelpPage from './pages/HelpPage'
import HomePage from './pages/HomePage'
import NormalizePage from './pages/NormalizePage'
import SearchPage from './pages/SearchPage'
import StatisticsPage from './pages/StatisticsPage'
import TagsPage from './pages/TagsPage'
import UsagePage from './pages/UsagePage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="files/:study" element={<FilesPage />} />
          <Route path="tags" element={<TagsPage />} />
          <Route path="statistics" element={<StatisticsPage />} />
          <Route path="help" element={<HelpPage />} />
          {/* Not under /api…: the dev server (and likely a production proxy)
              forwards every path starting with /api to the backend. */}
          <Route path="docs/api" element={<ApiDocsPage />} />
          {/* Admin only; linked at the far right of the menu. */}
          <Route path="admin/normalize" element={<NormalizePage />} />
          <Route path="admin/usage" element={<UsagePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
