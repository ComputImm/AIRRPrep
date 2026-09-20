# Preprocessing Frontend

## Prerequisites

Before running the project, make sure the following software is installed:

- Node.js 18 or newer (Recommended: Latest LTS)
- npm (comes with Node.js)
- Git (optional)

---

## Clone the Repository

Using SSH:

```bash
git clone git@github.com:fatemeh21ch/preprocessing_frontend.git
```

Or using HTTPS:

```bash
git clone https://github.com/fatemeh21ch/preprocessing_frontend.git
```

Move into the project directory:

```bash
cd preprocessing_frontend
```

---

## Install Dependencies

Install all required packages:

```bash
npm install
```

---

## Configure Environment Variables

If the project uses environment variables, create and configure the `.env` file before starting the application.

---

## Start the Development Server

Run the following command:

```bash
npm run dev
```

After the application starts, the development server will be available at a local address similar to:

```text
http://localhost:8080
```

> **Note:** The port may vary depending on your Vite configuration or if another application is already using the default port.

---

## Build for Production

To generate an optimized production build:

```bash
npm run build
```

The production files will be generated in the `dist/` directory.

---

## Preview the Production Build

To preview the production build locally:

```bash
npm run preview
```

---

## Project Structure

```text
preprocessing_frontend/
│
├── public/
├── src/
│   ├── assets/
│   ├── components/
│   ├── hooks/
│   ├── pages/
│   ├── services/
│   ├── App.jsx
│   └── main.jsx
│
├── package.json
├── package-lock.json
├── vite.config.js
└── README.md
```

---

## Notes

- Run the following command after cloning the repository:

  ```bash
  npm install
  ```

- Make sure the backend server is running before using the frontend.
