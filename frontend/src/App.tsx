import { BrowserRouter, Route, Routes } from 'react-router'
import AppLayout from './components/AppLayout'
import ApiDocsPage from './pages/ApiDocsPage'
import FilesPage from './pages/FilesPage'
import HomePage from './pages/HomePage'
import NormalizePage from './pages/NormalizePage'
import SearchPage from './pages/SearchPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="files/:study" element={<FilesPage />} />
          {/* Not under /api…: the dev server (and likely a production proxy)
              forwards every path starting with /api to the backend. */}
          <Route path="docs/api" element={<ApiDocsPage />} />
          {/* Admin only, reached by its address; not in the menu. */}
          <Route path="admin/normalize" element={<NormalizePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
