import express from 'express';
import { PythonShell } from 'python-shell';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const port = 3000;

app.use(express.json());

// Enable CORS
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');
  next();
});

app.get('/api/scrape', async (req, res) => {
  try {
    const options = {
      scriptPath: __dirname,
      pythonPath: 'python3'
    };

    const results = await PythonShell.run('scraper.py', options);
    const data = results[0] ? JSON.parse(results[0]) : [];
    res.json(data);
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ 
      error: 'Internal server error',
      details: error.message 
    });
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}`);
});