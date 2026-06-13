import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Product from './pages/Product';
import Clinicians from './pages/Clinicians';
import Company from './pages/Company';
import HowItWorks from './pages/HowItWorks';
import Pricing from './pages/Pricing';
import Demo from './pages/Demo';
import Integrations from './pages/Integrations';
import IntegrationGuide from './pages/IntegrationGuide';
import Security from './pages/Security';
import Hipaa from './pages/Hipaa';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Contact from './pages/Contact';
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
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/integrations/:slug" element={<IntegrationGuide />} />
          <Route path="/security" element={<Security />} />
          <Route path="/hipaa" element={<Hipaa />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/blog" element={<Navigate to="/how-it-works" replace />} />
          <Route path="/demo" element={<Demo />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
