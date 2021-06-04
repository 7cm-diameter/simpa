library(tidyverse)
library(cmdstanr)
library(rstan)


LICKON <- 7

to_fittable_data <- function(data, k) {
  data$time <- data$time - min(data$time)
  IRTs <- data %>%
    filter(event == LICKON) %>%
    (function(d) {
       diff(c(0, d$time))
    })
  return(list(y = IRTs, K = k, T = length(IRTs)))
}

fit_mcmc <- function(model, data, ...) {
  return(model$sample(data = data, ...))
}

fit_vb <- function(model, data, ...) {
  return(model$variational(data = data, ...))
}

extract_optimal_satet_seq <- function(stanfit) {
  extract <- extract(stanfit)
  return(extract$zstar[1, ])
}

is_converged <- function(stanfit) {
  return(all(summary(stanfit)$summary[, "Rhat"] <= 1.10, na.rm = T))
}

show_estimates <- function(fittable, state_seq) {
  states <- c("bout-initiation", "within-bout")
  state_seq <- states[state_seq]
  data.frame(time = cumsum(fittable$y),
             IRTs = fittable$y,
             state = state_seq) %>%
    ggplot() +
      geom_point(aes(x = t, y = IRTs, color = state))
}

to_saved_format <- function(fittable, state_seq) {
  data.frame(time = cumsum(fittable$y),
             IRTs = fittable$y,
             state = state_seq)
}

append_to_filestem <- function(filename, s, sep = "-") {
  splits <- basename(filename) %>% strsplit(., "\\.") %>% unlist
  filestem <- splits[1]
  extension <- splits[2]
  stem_new <- paste(filestem, s, sep = sep)
  return(paste(stem_new, extension, sep = "."))
}

extract_fr2lr <- function(data) {
  us_onsets <- data %>% filter(event == 112) %>% (function(d) d$time)
  first <- min(us_onsets)
  last <- max(us_onsets)
  data %>% filter(first <= time & time <= last)
}

# estimate bout-and-pause patterns

SAVE_DIR <- "./data/bouts"
filepaths <- list.files("./data/events", full.names = T)

results <- filepaths %>%
  lapply(., function(path) {
    data <- read.csv(path) %>% extract_fr2lr
    fittable_data <- to_fittable_data(data, 2)
    model <- cmdstan_model("./analysis/hmm.stan")

    fitted <- fit_mcmc(model, fittable_data,
                       parallel_chains = 4,
                       chains = 4,
                       iter_warmup = 500,
                       iter_sampling = 500)

    stanfit <- read_stan_csv(fitted$output_files())
    convergence <- is_converged(stanfit)
    state_seq <- extract_optimal_satet_seq(stanfit)

    estim <- show_estimates(fittable_data, state_seq)
    saved_data <- to_saved_format(fittable_data, state_seq)
    saved_path <- file.path(SAVE_DIR, append_to_filestem(basename(path), "bouts"))
    return(list(data = saved_data, path = saved_path, convergence = convergence, estim = estim))
  })

results %>%
  lapply(., function(l) {
    write.csv(l$data, l$path, row.names = F)
  })
