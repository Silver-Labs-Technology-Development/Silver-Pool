import { projects } from './projects.mjs'

const projectGrid = document.querySelector('#project-grid')

if (projectGrid) {
  projectGrid.innerHTML = projects.map((project, index) => {
    const repository = project.repo
      ? `<a class="project-repo" href="${project.repo}" target="_blank" rel="noopener noreferrer">${project.repoLabel} <span aria-hidden="true">↗</span></a>`
      : `<span class="project-repo project-repo-muted">${project.repoLabel}</span>`
    return `
      <article class="project-card">
        <div class="project-card-top">
          <span class="project-index">${String(index + 1).padStart(2, '0')}</span>
          <span class="status-pill status-${project.statusClass}">${project.status}</span>
        </div>
        <p class="project-category">${project.category}</p>
        <h3>${project.name}</h3>
        <p class="project-summary">${project.summary}</p>
        <p class="project-next"><strong>Next:</strong> ${project.next}</p>
        ${repository}
      </article>
    `
  }).join('')
}

const menuToggle = document.querySelector('.menu-toggle')
const navigation = document.querySelector('#primary-navigation')

if (menuToggle && navigation) {
  menuToggle.addEventListener('click', () => {
    const expanded = menuToggle.getAttribute('aria-expanded') === 'true'
    menuToggle.setAttribute('aria-expanded', String(!expanded))
    navigation.classList.toggle('is-open', !expanded)
  })

  navigation.addEventListener('click', (event) => {
    if (event.target instanceof HTMLAnchorElement) {
      menuToggle.setAttribute('aria-expanded', 'false')
      navigation.classList.remove('is-open')
    }
  })
}

const year = document.querySelector('#current-year')
if (year) year.textContent = String(new Date().getFullYear())
