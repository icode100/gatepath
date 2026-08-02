import type { LearningReference } from "./types";

const OFFICIAL_SYLLABUS: LearningReference = {
  title: "GATE 2027 CS syllabus",
  publisher: "IIT Madras",
  url: "https://gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/CS_GATE2027_Syllabus.pdf",
  note: "The syllabus boundary used for every technical chapter.",
};

const OFFICIAL_APTITUDE_SYLLABUS: LearningReference = {
  title: "GATE 2027 General Aptitude syllabus",
  publisher: "IIT Madras",
  url: "https://gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/GA_GATE2027_Syllabus.pdf",
  note: "The syllabus boundary used for verbal, quantitative, analytical and spatial aptitude.",
};

const nptel = (
  title: string,
  url: string,
  note: string,
): LearningReference => ({ title, publisher: "NPTEL", url, note });

export const LEARNING_REFERENCES: Record<string, LearningReference[]> = {
  EM: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Discrete Mathematics",
      "https://www.nptel.ac.in/courses/106108227",
      "IIT/IIIT faculty lectures for logic, sets, relations, graphs and combinatorics.",
    ),
    nptel(
      "Probability for Computer Science",
      "https://www.nptel.ac.in/courses/106104233",
      "IIT Kanpur lectures for probability, random variables and Bayes reasoning.",
    ),
  ],
  DL: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Digital Circuits",
      "https://www.nptel.ac.in/courses/108105113",
      "IIT Kharagpur coverage of Boolean algebra, combinational logic and sequential circuits.",
    ),
  ],
  COA: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Computer Organization and Architecture",
      "https://nptel.ac.in/courses/106103068",
      "IIT Guwahati lectures on instruction sets, datapaths, memory, I/O and pipelining.",
    ),
  ],
  PDS: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Programming and Data Structures",
      "https://nptel.ac.in/courses/106106130",
      "IIT Madras lectures using C for arrays, lists, stacks, queues, trees and heaps.",
    ),
  ],
  ALG: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Fundamental Algorithms: Design and Analysis",
      "https://www.nptel.ac.in/courses/106105157",
      "IIT Kharagpur lectures on asymptotics, design paradigms and graph algorithms.",
    ),
  ],
  TOC: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Theory of Computation",
      "https://www.nptel.ac.in/courses/106104028",
      "IIT Kanpur lectures on automata, grammars, pumping arguments and Turing machines.",
    ),
  ],
  CD: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Compiler Design",
      "https://www.nptel.ac.in/courses/106105190",
      "NPTEL course aligned to compiler front ends, runtime environments and optimization.",
    ),
  ],
  OS: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Operating System Fundamentals",
      "https://www.nptel.ac.in/courses/106105214",
      "IIT Kharagpur lectures on processes, synchronization, scheduling, memory and files.",
    ),
  ],
  DBMS: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Introduction to Database Systems",
      "https://www.nptel.ac.in/courses/106106220",
      "IIT Madras lectures on relational design, SQL, indexing and transactions.",
    ),
  ],
  CN: [
    OFFICIAL_SYLLABUS,
    nptel(
      "Computer Networks and Internet Protocol",
      "https://www.nptel.ac.in/courses/106105183",
      "IIT Kharagpur lectures covering the TCP/IP stack and the protocols in the GATE scope.",
    ),
  ],
  GA: [
    OFFICIAL_APTITUDE_SYLLABUS,
    {
      title: "NPTEL GATE Portal",
      publisher: "NPTEL",
      url: "https://gate.nptel.ac.in/",
      note: "IIT/IISc GATE preparation portal with mapped concept and assessment resources.",
    },
  ],
};

