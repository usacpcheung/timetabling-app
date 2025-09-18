/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
    "./static/**/*.html",
    "./node_modules/flowbite/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        emerald: {
          25: '#f6fefb'
        }
      }
    }
  },
  plugins: [require('flowbite/plugin')]
};
