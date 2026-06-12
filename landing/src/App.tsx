import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Product from './pages/Product';
import Clinicians from './pages/Clinicians';
import Company from './pages/Company';
import HowItWorks from './pages/HowItWorks';
import Pricing from './pages/Pricing';
import Demo from './pages/Demo';
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Product />} />
          <Route path="/product" element={<Navigate to="/" replace />} />
          <Route path="/clinicians" element={<Clinicians />} />
          <Route path="/company" element={<Company />} />
          <Route path="/how-it-works" element={<HowItWorks />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/blog" element={<Navigate to="/how-it-works" replace />} />
          <Route path="/demo" element={<Demo />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
