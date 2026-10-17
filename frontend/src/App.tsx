import { BrowserRouter, Route, Routes } from 'react-router'
import AppLayout from './components/AppLayout'
import FilesPage from './pages/FilesPage'
import HomePage from './pages/HomePage'
import SearchPage from './pages/SearchPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="files/:study" element={<FilesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
