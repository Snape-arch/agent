import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import './styles.css';
import '../../static/assets/color-system.css';
import './clawos-theme.css';
import '../../static/assets/type-system.css';
import '../../static/assets/context-help.js';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
