pipeline {
  agent any
  stages {
    stage('Test') {
      steps {
        sh 'python3 -m pip install -r requirements-dev.txt'
        sh 'python3 -m pytest -q'
      }
    }
    stage('Docker Build') {
      steps { sh 'docker build -t rollit:${BUILD_NUMBER} .' }
    }
    stage('Image Sanity') {
      steps { sh 'docker image inspect rollit:${BUILD_NUMBER} >/dev/null' }
    }
  }
}
